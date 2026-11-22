"""课堂 PK 容量探针（dev-only，设计稿 `docs/vocabulary-pk-farm-design-20261122.md` §1.3）。

在专用合成库 `app_pk_probe` 上起 20 名学生 / 10 场 1v1，测量：

- 作答接口延迟（本机参考环境目标 P95 ≤ 300 ms）；
- 状态传播延迟：服务端状态变更 → 客户端 SSE 可见（目标 P95 ≤ 1.5 s）；
- 并发通道：20 条对局 SSE + 20 条轮询快照通道（合计 40），保持 `--hold-seconds`。

口径说明：

- 探针内部临时起一个单 worker uvicorn（ephemeral 端口），httpx 走真实 TCP，
  避免 ASGI 测试传输缓冲 SSE 响应体；不触碰 8001/5175 上的既有进程。
- 测量值只反映本机参考环境，不作为线上容量承诺。
- 不写 `VocabularyAnswer`、不触教师任务统计；合成数据跑完随库清理。
- 本脚本不入 CI lint / 无 runbook（与 `perf_baseline.py` 同类 dev-only 工具）。

用法：

  POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \\
    .venv/bin/python scripts/pk_capacity_probe.py
  # 可选：--players 20 --hold-seconds 60 --keep-db --port 8003
"""

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# 必须在导入 app 之前屏蔽真实评分调用（与 tests/conftest.py 同口径）
os.environ.setdefault("SCORING_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROBE_DB_NAME = "app_pk_probe"
PROBE_CODE = "PKPROBE"
PROBE_PASSWORD = "probe-pass-12345"
ANSWER_TARGET_MS = 300.0
PROPAGATION_TARGET_S = 1.5
PROPAGATION_TIMEOUT_S = 3.0
POLL_INTERVAL_S = 1.5

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _refuse_unsafe_target() -> None:
    """安全闸：仅 local 环境 + 本机实例；避免误指远端。"""
    from app.core.config import settings

    if settings.ENVIRONMENT != "local":
        raise SystemExit(
            f"仅允许 ENVIRONMENT=local 运行（当前 {settings.ENVIRONMENT}）"
        )
    parsed = urlparse(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    if parsed.hostname not in _LOCAL_HOSTS:
        raise SystemExit(f"目标实例不是本机（{parsed.hostname}），拒绝运行")


def _probe_uri() -> tuple[str, str]:
    """从测试 DSN 派生同实例管理库与探针库 URI。"""
    from app.core.config import settings

    parsed = urlparse(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    admin_uri = urlunparse(parsed._replace(path="/postgres"))
    probe_uri = urlunparse(parsed._replace(path=f"/{PROBE_DB_NAME}"))
    return admin_uri, probe_uri


def _prepare_database():
    """创建本次专用探针库；`--keep-db` 时保留。返回 engine。"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    admin_uri, probe_uri = _probe_uri()
    admin = create_engine(admin_uri, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{PROBE_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{PROBE_DB_NAME}"'))
    admin.dispose()

    from app.core.tenant_context import install_tenant_bind

    # 池上限对齐 40 通道 + 作答并发；单 worker 前提（设计稿 §1.2）
    engine = create_engine(probe_uri, pool_pre_ping=True, pool_size=20, max_overflow=20)
    install_tenant_bind(engine)
    return engine


def _seed(engine, players: int) -> dict[str, object]:
    """合成地基：默认租户 + 教师 + 课堂 + 学生账号与档案。词库走 API 创建。"""
    from sqlmodel import Session, SQLModel

    from app.core.security import get_password_hash
    from app.models import DEFAULT_TENANT_ID, Classroom, Student, Tenant, User

    SQLModel.metadata.create_all(engine)
    teacher_email = "pk-probe-teacher@local.test"
    with Session(engine) as session:
        session.add(
            Tenant(id=DEFAULT_TENANT_ID, slug="pk-probe", name_zh="PK 探针租户")
        )
        session.flush()
        teacher = User(
            email=teacher_email,
            full_name="PK 探针教师",
            role="teacher",
            hashed_password=get_password_hash(PROBE_PASSWORD),
        )
        session.add(teacher)
        session.flush()
        classroom = Classroom(
            code=PROBE_CODE,
            name="PK 探针课堂",
            class_size=max(players, 40),
            owner_id=teacher.id,
        )
        session.add(classroom)
        session.flush()
        classroom_id = str(classroom.id)

        students: list[dict[str, object]] = []
        for i in range(players):
            username = f"pkstu{i:02d}"
            user = User(
                username=username,
                full_name=f"玩家{i:02d}",
                role="student",
                hashed_password=get_password_hash(PROBE_PASSWORD),
            )
            session.add(user)
            session.flush()
            student = Student(
                classroom_id=classroom.id,
                user_id=user.id,
                display_name=f"玩家{i:02d}",
            )
            session.add(student)
            session.flush()
            students.append({"username": username, "student_id": str(student.id)})
        session.commit()
    return {
        "teacher_email": teacher_email,
        "classroom_id": classroom_id,
        "students": students,
    }


def _pct(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))
    return ordered[idx]


def _fmt_ms(value: float) -> str:
    return f"{value:.1f} ms"


def _start_server(app, port: int) -> tuple[object, threading.Thread, str]:
    """后台线程起单 worker uvicorn；返回 (server, thread, base_url)。"""
    import uvicorn

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error", lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    sock = server.servers[0].sockets[0]
    base_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    return server, thread, base_url


async def _login(client, username: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/login/access-token",
        data={"username": username, "password": PROBE_PASSWORD},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _subscribe_sse(
    client,
    headers: dict[str, str],
    match_id: str,
    sink: list[tuple[float, dict]],
    stop: asyncio.Event,
    errors: list[str],
) -> None:
    try:
        async with client.stream(
            "GET",
            f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/events",
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if stop.is_set():
                    break
                if line.startswith("data:"):
                    try:
                        sink.append((time.monotonic(), json.loads(line[5:].strip())))
                    except json.JSONDecodeError:
                        continue
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 探针记录错误，不中断主流程
        errors.append(f"SSE {match_id}: {exc}")


async def run_probe(args: argparse.Namespace) -> int:
    from app.core.db import set_engine

    engine = _prepare_database()
    set_engine(engine)
    seed = _seed(engine, args.players)
    classroom_id = seed["classroom_id"]
    students = seed["students"]

    import httpx

    from app.main import app

    server, server_thread, base_url = _start_server(app, args.port)
    client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    answer_latencies_ms: list[float] = []
    propagation_s: list[float] = []
    propagation_errors: list[str] = []
    channel_errors: list[str] = []
    sse_channels = 0
    poll_channels = 0

    try:
        teacher_headers = await _login(client, str(seed["teacher_email"]))

        words = [
            {
                "headword": f"probe{i:03d}",
                "part_of_speech": "n.",
                "meaning_zh": f"探针义{i}",
            }
            for i in range(max(args.players, 12))
        ]
        book_resp = await client.post(
            "/api/v1/vocabulary/books",
            headers=teacher_headers,
            json={
                "title": "PK 探针词库",
                "scope": "classroom",
                "classroom_id": classroom_id,
                "words": words,
            },
        )
        book_resp.raise_for_status()
        book = book_resp.json()
        spelling = {w["meaning_zh"]: w["headword"] for w in book["words"]}

        lobby_resp = await client.post(
            f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/lobby",
            headers=teacher_headers,
            json={
                "book_id": book["id"],
                "question_count": 8,
                "per_question_seconds": 20,
                "prompt_types": ["meaning"],
            },
        )
        lobby_resp.raise_for_status()

        # 学生登录 + 加入排队；先加入方的首次响应可能尚未带上 match_id，
        # 配对完成后再拉一次大厅快照补齐对局归属。
        player_clients: list[dict[str, object]] = []
        for student in students:
            headers = await _login(client, str(student["username"]))
            join_resp = await client.post(
                f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/lobby/join",
                headers=headers,
            )
            join_resp.raise_for_status()
            player_clients.append(
                {
                    "headers": headers,
                    "student_id": str(student["student_id"]),
                    "match_id": None,
                }
            )

        for player in player_clients:
            lobby = (
                await client.get(
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/lobby",
                    headers=player["headers"],
                )
            ).json()
            player["match_id"] = lobby.get("my_match_id")

        matches: dict[str, list[dict[str, object]]] = {}
        for player in player_clients:
            matches.setdefault(str(player["match_id"]), []).append(player)
        active_matches = {
            match_id: pair
            for match_id, pair in matches.items()
            if match_id != "None" and match_id is not None
        }
        print(
            f"\n规模：{len(player_clients)} 玩家 / {len(active_matches)} 场 1v1"
            f"（目标 20 玩家 / 10 场）· 服务 {base_url}\n"
        )

        # ── 作答延迟：每名玩家提交第 1 题正确答案 ──────────────────────────
        async def _answer_first(player: dict[str, object]) -> None:
            headers = player["headers"]
            match_id = str(player["match_id"])
            state = await client.get(
                f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                headers=headers,
            )
            state.raise_for_status()
            item = state.json()["items"][0]
            answer = spelling[item["meaning_zh"]]
            started = time.monotonic()
            resp = await client.post(
                f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/answers",
                headers=headers,
                json={
                    "item_index": 0,
                    "prompt_type": "meaning",
                    "answer": answer,
                    "idempotency_key": f"probe-{player['student_id']}-0",
                },
            )
            resp.raise_for_status()
            answer_latencies_ms.append((time.monotonic() - started) * 1000)

        await asyncio.gather(*(_answer_first(p) for p in player_clients))

        # ── 传播延迟：抽样对局，对手 SSE 收到新版本快照的耗时 ──────────────
        sample_matches = list(active_matches.items())[: args.propagation_matches]
        for match_id, pair in sample_matches:
            side_a, side_b = pair[0], pair[1]
            baseline = (
                await client.get(
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                    headers=side_b["headers"],
                )
            ).json()
            baseline_version = baseline["state_version"]
            sink: list[tuple[float, dict]] = []
            stop = asyncio.Event()
            sub_task = asyncio.create_task(
                _subscribe_sse(
                    client, side_b["headers"], match_id, sink, stop, propagation_errors
                )
            )

            a_state = (
                await client.get(
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                    headers=side_a["headers"],
                )
            ).json()
            a_answer = spelling[a_state["items"][1]["meaning_zh"]]
            a_submit = await client.post(
                f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/answers",
                headers=side_a["headers"],
                json={
                    "item_index": 1,
                    "prompt_type": "meaning",
                    "answer": a_answer,
                    "idempotency_key": f"probe-{side_a['student_id']}-1",
                },
            )
            a_submit.raise_for_status()

            b_state = (
                await client.get(
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                    headers=side_b["headers"],
                )
            ).json()
            b_answer = spelling[b_state["items"][1]["meaning_zh"]]
            b_submit = await client.post(
                f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/answers",
                headers=side_b["headers"],
                json={
                    "item_index": 1,
                    "prompt_type": "meaning",
                    "answer": b_answer,
                    "idempotency_key": f"probe-{side_b['student_id']}-1",
                },
            )
            b_submit.raise_for_status()
            t0 = time.monotonic()

            delta: float | None = None
            deadline = t0 + PROPAGATION_TIMEOUT_S
            while time.monotonic() < deadline:
                for event_at, snapshot in sink:
                    if (
                        snapshot.get("state_version", baseline_version)
                        > baseline_version
                    ):
                        delta = event_at - t0
                        break
                if delta is not None:
                    break
                await asyncio.sleep(0.05)
            stop.set()
            sub_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sub_task
            if delta is None:
                propagation_errors.append(f"传播超时 {match_id}")
            else:
                propagation_s.append(delta)

        # ── 并发通道保持：20 SSE + 20 轮询，保持 hold-seconds ─────────────
        hold_stop = asyncio.Event()
        sse_ready = asyncio.Event()
        expected_sse = len(player_clients)

        async def _hold_sse(player: dict[str, object]) -> None:
            nonlocal sse_channels
            match_id = str(player["match_id"])
            try:
                async with client.stream(
                    "GET",
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/events",
                    headers=player["headers"],
                ) as resp:
                    resp.raise_for_status()
                    sse_channels += 1
                    if sse_channels == expected_sse:
                        sse_ready.set()
                    async for line in resp.aiter_lines():
                        if hold_stop.is_set():
                            break
                        _ = line
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                channel_errors.append(f"SSE hold {match_id}: {exc}")

        async def _hold_poll(player: dict[str, object]) -> None:
            nonlocal poll_channels
            match_id = str(player["match_id"])
            try:
                poll_channels += 1
                while not hold_stop.is_set():
                    resp = await client.get(
                        f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                        headers=player["headers"],
                    )
                    resp.raise_for_status()
                    await asyncio.wait_for(hold_stop.wait(), POLL_INTERVAL_S)
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                channel_errors.append(f"poll hold {match_id}: {exc}")

        sse_tasks = [asyncio.create_task(_hold_sse(p)) for p in player_clients]
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(sse_ready.wait(), timeout=10)
        poll_tasks = [asyncio.create_task(_hold_poll(p)) for p in player_clients]
        await asyncio.sleep(args.hold_seconds)
        hold_stop.set()
        for task in sse_tasks + poll_tasks:
            task.cancel()
        await asyncio.gather(*(sse_tasks + poll_tasks), return_exceptions=True)

        # ── 报告 ──────────────────────────────────────────────────────────
        answer_p50 = _pct(answer_latencies_ms, 0.50)
        answer_p95 = _pct(answer_latencies_ms, 0.95)
        prop_p50 = statistics.median(propagation_s) if propagation_s else 0.0
        prop_p95 = _pct(propagation_s, 0.95)

        print("| 指标 | 实测 | 目标 | 判定 |")
        print("|---|---|---|---|")
        answer_ok = answer_p95 <= ANSWER_TARGET_MS
        print(
            f"| 作答接口延迟（n={len(answer_latencies_ms)}） | "
            f"P50 {_fmt_ms(answer_p50)} / P95 {_fmt_ms(answer_p95)} | "
            f"P95 ≤ {_fmt_ms(ANSWER_TARGET_MS)} | {'达标' if answer_ok else '超目标'} |"
        )
        prop_ok = prop_p95 <= PROPAGATION_TARGET_S
        print(
            f"| 状态传播延迟（n={len(propagation_s)}） | "
            f"P50 {prop_p50:.2f}s / P95 {prop_p95:.2f}s | "
            f"P95 ≤ {PROPAGATION_TARGET_S}s | {'达标' if prop_ok else '超目标'} |"
        )
        channel_total = sse_channels + poll_channels
        print(
            f"| 并发通道 | SSE {sse_channels} 条 · 轮询 {poll_channels} 条 "
            f"（合计 {channel_total}），保持 {args.hold_seconds}s | "
            f"40 条 / 60s | {'达标' if channel_total >= 40 else '不足'} |"
        )

        if propagation_errors or channel_errors:
            print("\n通道异常：")
            for err in propagation_errors + channel_errors:
                print(f"  - {err}")

        print(
            "\n注：以上为本机参考环境实测值；线上容量需按部署规格复测。"
            "多 worker 部署时以前端轮询快照为准（设计稿 §1.2）。"
        )
        return 0 if answer_ok and prop_ok and channel_total >= 40 else 1
    finally:
        set_engine(None)
        with contextlib.suppress(Exception):
            server.should_exit = True
            server_thread.join(timeout=5)
        await client.aclose()
        engine.dispose()
        if not args.keep_db:
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool

            admin_uri, _ = _probe_uri()
            admin = create_engine(
                admin_uri, isolation_level="AUTOCOMMIT", poolclass=NullPool
            )
            with admin.connect() as conn:
                conn.execute(
                    text(f'DROP DATABASE IF EXISTS "{PROBE_DB_NAME}" WITH (FORCE)')
                )
            admin.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=int, default=20)
    parser.add_argument("--hold-seconds", type=int, default=60)
    parser.add_argument(
        "--propagation-matches",
        type=int,
        default=5,
        help="抽样测量传播延迟的对局数（其余只计入并发通道）",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="临时 uvicorn 端口（0=随机）"
    )
    parser.add_argument("--keep-db", action="store_true", help="保留探针库便于排查")
    args = parser.parse_args()
    _refuse_unsafe_target()
    return asyncio.run(run_probe(args))


if __name__ == "__main__":
    raise SystemExit(main())
