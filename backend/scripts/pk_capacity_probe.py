"""课堂 PK 容量探针（dev-only，设计稿 `docs/vocabulary-pk-farm-design-20261122.md` §1.3）。

在专用合成库 `app_pk_probe` 上起 20 名学生 / 10 场 1v1，测量：

- 作答接口延迟（本机参考环境目标 P95 ≤ 300 ms）；
- 状态传播延迟：服务端状态变更 → 客户端 SSE 可见（目标 P95 ≤ 1.5 s）；
- 并发通道：20 条对局 SSE + 20 条轮询快照通道（合计 40），保持 `--hold-seconds`。

两种副本形态（`--replicas`）：

- ``1``（单副本基线）：探针内部临时起一个单 worker uvicorn（ephemeral 端口），
  httpx 走真实 TCP；不触碰 8000/5173 上的既有开发进程。
- ``2``（双副本）：拉起两个**独立 OS 子进程**（`pk_probe_server.py`），
  共享同一本地探针库；作答与通道尽量跨副本分布，单独标注跨副本传播样本。
  不用「同一进程两个线程」冒充副本。

环境口径（三类数字严格区分，本机数字不写成生产承诺）：

- 本机单副本：`--replicas 1`，开发机 + 本地 Docker Postgres(5433)；
- 本机双副本：`--replicas 2`，同上，两进程共库；
- 目标环境：预发/测试或生产同规格非生产环境复测（本脚本的安全闸拒绝连远端，
  目标环境复测走独立 runbook，见 `docs/qa/20261125/d-capacity/README.md`）。

其他口径：

- 不写 `VocabularyAnswer`、不触教师任务统计；合成数据跑完随库清理。
- 本脚本不入 CI lint / 无 runbook（与 `perf_baseline.py` 同类 dev-only 工具）。

用法：

  export PK_PROBE_PASSWORD="<本机合成库临时口令>"
  POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \\
    .venv/bin/python scripts/pk_capacity_probe.py --replicas 1
  POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \\
    .venv/bin/python scripts/pk_capacity_probe.py --replicas 2
  # 可选：--players 20 --hold-seconds 60 --keep-db --port 8003

探针教师/学生账号口令取自环境变量 ``PK_PROBE_PASSWORD``，脚本不内置默认弱口令；
未设置或为空时打印用法并以非 0 退出。口令仅用于本机合成库，跑完随库清理，不写日志。
"""

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import subprocess
import sys
import threading
import time

import httpx
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# 必须在导入 app 之前屏蔽真实评分调用（与 tests/conftest.py 同口径）
os.environ.setdefault("SCORING_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROBE_DB_NAME = "app_pk_probe"
PROBE_CODE = "PKPROBE"
PROBE_PASSWORD_ENV = "PK_PROBE_PASSWORD"
# 运行前由 _require_probe_password() 从环境变量填入；不提供默认弱口令。
PROBE_PASSWORD = ""
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


def _require_probe_password() -> None:
    """从环境变量读取探针临时账号口令；未设置/为空时拒绝运行（不提供默认弱口令）。"""
    global PROBE_PASSWORD
    password = os.environ.get(PROBE_PASSWORD_ENV, "").strip()
    if not password:
        raise SystemExit(
            f"未设置环境变量 {PROBE_PASSWORD_ENV}：请先导出探针临时账号口令再运行"
            "（口令仅用于本机合成库，跑完随库清理；脚本不提供默认弱口令）。"
        )
    PROBE_PASSWORD = password


def _probe_uri() -> tuple[str, str]:
    """从测试 DSN 派生同实例管理库与探针库 URI。"""
    from app.core.config import settings

    parsed = urlparse(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    admin_uri = urlunparse(parsed._replace(path="/postgres"))
    probe_uri = urlunparse(parsed._replace(path=f"/{PROBE_DB_NAME}"))
    return admin_uri, probe_uri


def _prepare_database():
    """创建本次专用探针库；`--keep-db` 时保留。返回 (engine, probe_uri)。"""
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
    return engine, probe_uri


def _seed(engine, players: int) -> dict[str, object]:
    """合成地基：默认租户 + 教师 + 课堂 + 学生账号与档案。词库走 API 创建。"""
    from sqlmodel import Session, SQLModel

    from app.core.security import get_password_hash
    from app.models import (
        DEFAULT_TENANT_ID,
        MODULE_SPEAKING,
        MODULE_VOCABULARY,
        Classroom,
        Student,
        Tenant,
        TenantModule,
        User,
    )

    SQLModel.metadata.create_all(engine)
    teacher_email = "pk-probe-teacher@local.test"
    with Session(engine) as session:
        session.add(
            Tenant(id=DEFAULT_TENANT_ID, slug="pk-probe", name_zh="PK 探针租户")
        )
        session.flush()
        # 探针租户显式双开模块（探针库不走 init_db 种子，缺行会被授权门 403）
        for module_key in (MODULE_SPEAKING, MODULE_VOCABULARY):
            session.add(
                TenantModule(
                    tenant_id=DEFAULT_TENANT_ID,
                    module_key=module_key,
                    enabled=True,
                )
            )
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


def _free_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@dataclass
class Replica:
    """一个后端副本；单副本模式走线程内 uvicorn，双副本走独立子进程。"""

    index: int
    base_url: str
    proc: subprocess.Popen | None = None
    thread: threading.Thread | None = None
    server: object | None = None


def _start_inthread_server(app, port: int) -> tuple[object, threading.Thread, str]:
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


async def _wait_healthy(base_url: str, timeout_s: float = 15.0) -> None:
    """轮询 liveness 端点直到进程响应（不触库；DB 连通性由首个业务请求验证）。"""
    import httpx

    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=3.0) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get("/api/v1/utils/health-check/")
                if resp.status_code == 200:
                    return
            except Exception:  # noqa: BLE001 - 进程尚未起来，继续等待
                pass
            await asyncio.sleep(0.1)
    raise SystemExit(f"副本未在 {timeout_s}s 内就绪：{base_url}")


async def _start_replicas(
    args: argparse.Namespace, probe_uri: str
) -> list[Replica]:
    """按 --replicas 拉起 1（线程内基线）或 2（独立子进程）个副本。"""
    from app.main import app

    replicas: list[Replica] = []
    if args.replicas == 1:
        server, thread, base_url = _start_inthread_server(app, args.port)
        replicas.append(Replica(0, base_url, thread=thread, server=server))
        return replicas

    for replica_id in range(args.replicas):
        port = _free_port()
        env = {
            **os.environ,
            "PK_PROBE_DATABASE_URI": probe_uri,
            "PK_PROBE_PORT": str(port),
            "PK_PROBE_REPLICA_ID": str(replica_id),
        }
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).parent / "pk_probe_server.py")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base_url = f"http://127.0.0.1:{port}"
        await _wait_healthy(base_url)
        replicas.append(Replica(replica_id, base_url, proc=proc))
    return replicas


async def _login(clients: list[httpx.AsyncClient], replica: int, username: str) -> dict[str, str]:
    resp = await clients[replica].post(
        "/api/v1/login/access-token",
        data={"username": username, "password": PROBE_PASSWORD},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _subscribe_sse(
    client: httpx.AsyncClient,
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

    engine, probe_uri = _prepare_database()
    set_engine(engine)
    seed = _seed(engine, args.players)
    classroom_id = seed["classroom_id"]
    students = seed["students"]

    replicas = await _start_replicas(args, probe_uri)
    clients = [httpx.AsyncClient(base_url=r.base_url, timeout=30.0) for r in replicas]
    replica_count = len(replicas)
    rr = {"n": 0}

    def next_replica() -> int:
        idx = rr["n"] % replica_count
        rr["n"] += 1
        return idx

    answer_latencies_ms: list[float] = []
    answer_replicas: list[int] = []
    propagation_s: list[float] = []
    propagation_cross: list[float] = []
    propagation_errors: list[str] = []
    channel_errors: list[str] = []
    sse_channels = 0
    poll_channels = 0

    try:
        teacher_replica = 0
        teacher_headers = await _login(clients, teacher_replica, str(seed["teacher_email"]))

        words = [
            {
                "headword": f"probe{i:03d}",
                "part_of_speech": "n.",
                "meaning_zh": f"探针义{i}",
            }
            for i in range(max(args.players, 12))
        ]
        book_resp = await clients[teacher_replica].post(
            "/api/v1/vocabulary/books",
            headers=teacher_headers,
            json={
                "title": "PK 探针词库",
                "scope": "classroom",
                "classroom_id": classroom_id,
                "words": words,
                "confirm_reviewed": True,
            },
        )
        book_resp.raise_for_status()
        book = book_resp.json()
        spelling = {w["meaning_zh"]: w["headword"] for w in book["words"]}

        lobby_resp = await clients[teacher_replica].post(
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

        # 学生登录 + 加入排队；尽量跨副本分布。先加入方的首次响应可能尚未带上
        # match_id，配对完成后再拉一次大厅快照补齐对局归属。
        player_clients: list[dict[str, object]] = []
        for student in students:
            replica = next_replica()
            headers = await _login(clients, replica, str(student["username"]))
            join_resp = await clients[replica].post(
                f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/lobby/join",
                headers=headers,
            )
            join_resp.raise_for_status()
            player_clients.append(
                {
                    "headers": headers,
                    "student_id": str(student["student_id"]),
                    "match_id": None,
                    "replica": replica,
                }
            )

        for player in player_clients:
            replica = int(player["replica"])
            lobby = (
                await clients[replica].get(
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
        replica_dist = ", ".join(
            f"副本{r.index} {sum(p['replica'] == r.index for p in player_clients)} 人"
            for r in replicas
        )
        print(
            f"\n规模：{len(player_clients)} 玩家 / {len(active_matches)} 场 1v1"
            f"（目标 20 玩家 / 10 场）· 副本数 {replica_count}（{replica_dist}）\n"
        )

        # ── 作答延迟：每名玩家提交第 1 题正确答案 ──────────────────────────
        async def _answer_first(player: dict[str, object]) -> None:
            headers = player["headers"]
            replica = int(player["replica"])
            match_id = str(player["match_id"])
            state = await clients[replica].get(
                f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                headers=headers,
            )
            state.raise_for_status()
            item = state.json()["items"][0]
            answer = spelling[item["meaning_zh"]]
            started = time.monotonic()
            resp = await clients[replica].post(
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
            answer_replicas.append(replica)

        await asyncio.gather(*(_answer_first(p) for p in player_clients))

        # ── 传播延迟：抽样对局，对手 SSE 收到新版本快照的耗时 ──────────────
        sample_matches = list(active_matches.items())[: args.propagation_matches]
        for match_id, pair in sample_matches:
            side_a, side_b = pair[0], pair[1]
            watcher_replica = int(side_b["replica"])
            # 提交方尽量走与观察者不同的副本（双副本下即跨副本样本）
            submit_replica = (
                1 - watcher_replica if replica_count > 1 else watcher_replica
            )
            baseline = (
                await clients[watcher_replica].get(
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                    headers=side_b["headers"],
                )
            ).json()
            baseline_version = baseline["state_version"]
            sink: list[tuple[float, dict]] = []
            stop = asyncio.Event()
            sub_task = asyncio.create_task(
                _subscribe_sse(
                    clients[watcher_replica],
                    side_b["headers"],
                    match_id,
                    sink,
                    stop,
                    propagation_errors,
                )
            )

            a_state = (
                await clients[submit_replica].get(
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                    headers=side_a["headers"],
                )
            ).json()
            a_answer = spelling[a_state["items"][1]["meaning_zh"]]
            a_submit = await clients[submit_replica].post(
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
                await clients[watcher_replica].get(
                    f"/api/v1/classes/{PROBE_CODE}/vocabulary/pk/matches/{match_id}/state",
                    headers=side_b["headers"],
                )
            ).json()
            b_answer = spelling[b_state["items"][1]["meaning_zh"]]
            b_submit = await clients[watcher_replica].post(
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
                if submit_replica != watcher_replica:
                    propagation_cross.append(delta)

        # ── 并发通道保持：20 SSE + 20 轮询，保持 hold-seconds ─────────────
        hold_stop = asyncio.Event()
        sse_ready = asyncio.Event()
        expected_sse = len(player_clients)

        async def _hold_sse(player: dict[str, object]) -> None:
            nonlocal sse_channels
            match_id = str(player["match_id"])
            replica = int(player["replica"])
            try:
                async with clients[replica].stream(
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
            replica = int(player["replica"])
            try:
                poll_channels += 1
                while not hold_stop.is_set():
                    resp = await clients[replica].get(
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
        cross_p95 = _pct(propagation_cross, 0.95) if propagation_cross else None
        answer_dist = {
            r.index: answer_replicas.count(r.index) for r in replicas
        }

        print(f"\n== 容量报告（{args.label} · {replica_count} 副本） ==")
        print("| 指标 | 实测 | 目标 | 判定 |")
        print("|---|---|---|---|")
        answer_ok = answer_p95 <= ANSWER_TARGET_MS
        print(
            f"| 作答接口延迟（n={len(answer_latencies_ms)}） | "
            f"P50 {_fmt_ms(answer_p50)} / P95 {_fmt_ms(answer_p95)} | "
            f"P95 ≤ {_fmt_ms(ANSWER_TARGET_MS)} | {'达标' if answer_ok else '超目标'} |"
        )
        dist_str = ", ".join(f"副本{k} {v} 笔" for k, v in sorted(answer_dist.items()))
        print(f"| 作答副本分布 | {dist_str} | — | — |")
        prop_ok = prop_p95 <= PROPAGATION_TARGET_S
        cross_note = (
            f"；跨副本 n={len(propagation_cross)} P95 {cross_p95:.2f}s"
            if propagation_cross
            else ""
        )
        print(
            f"| 状态传播延迟（n={len(propagation_s)}） | "
            f"P50 {prop_p50:.2f}s / P95 {prop_p95:.2f}s{cross_note} | "
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
        return (
            0
            if answer_ok and prop_ok and channel_total >= 40
            else 1
        )
    finally:
        set_engine(None)
        for client in clients:
            await client.aclose()
        for replica in replicas:
            if replica.proc is not None:
                replica.proc.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    replica.proc.wait(timeout=5)
                if replica.proc.poll() is None:
                    replica.proc.kill()
            if replica.server is not None:
                with contextlib.suppress(Exception):
                    replica.server.should_exit = True
            if replica.thread is not None:
                replica.thread.join(timeout=5)
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
        "--replicas",
        type=int,
        choices=(1, 2),
        default=1,
        help="1=线程内单副本基线；2=两个独立子进程共库双副本",
    )
    parser.add_argument(
        "--label",
        default="local",
        help="报告环境标注（local-single / local-dual / target-*），不改变任何行为",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="单副本模式临时 uvicorn 端口（0=随机）"
    )
    parser.add_argument("--keep-db", action="store_true", help="保留探针库便于排查")
    args = parser.parse_args()
    _refuse_unsafe_target()
    _require_probe_password()
    return asyncio.run(run_probe(args))


if __name__ == "__main__":
    raise SystemExit(main())
