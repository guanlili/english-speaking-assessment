"""本地性能基线：合成数据下测量热路径的查询数 / 加载行数 / 耗时。

用途（wise-quarry-trout 批次07）：先列实测瓶颈，再决定是否需要进一步
分页/缓存/索引——不凭猜测优化。测量目标：

1. worker.sweep_orphans 的 DONE 候选加载（学期累积的旧 done + 少量 pending）
2. vocabulary list_books 的可见性行加载
3. teacher_assignment_rows（词汇任务全历史轮次/首答）
4. wrong_word_items（学生 today 为 wrong_word_count 构造的完整错词本）

安全：只在独立的 app_perf 库上运行（自动创建/销毁），绝不指向开发库
（app）或测试库（app_test）；数据全部合成。

用法：
  POSTGRES_SERVER=localhost POSTGRES_PORT=5433 uv run python scripts/perf_baseline.py
  # 可选规模参数：--students 40 --old-done 10000 --pending 5 --books 200

维护承诺（2026-10-11 决策 B）：本脚本为 **dev-only** 工具——不入 CI lint、
无 runbook、已移出保活测试（backend/tests/scripts/test_*.py 对应文件已删）。
使用前请自行核对本文件与当前数据库 schema 是否仍然匹配。
"""

import argparse
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PERF_DB_NAME = "app_perf"


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _perf_uris() -> tuple[str, str]:
    """从应用测试 DSN 派生同实例凭据，库固定为 app_perf（返回 admin/perf DSN）。"""
    from urllib.parse import urlparse, urlunparse

    from app.core.config import settings

    parsed = urlparse(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    admin_uri = urlunparse(parsed._replace(path="/postgres"))
    perf_uri = urlunparse(parsed._replace(path=f"/{PERF_DB_NAME}"))
    return admin_uri, perf_uri


def _refuse_unsafe_target() -> None:
    """首个 DDL 前的安全闸（返修R02）：

    - 仅 ENVIRONMENT=local；
    - 目标必须是本机实例（localhost/127.0.0.1/::1）——防止 .env 指向
      远端时误删远端同名库；
    - 应用库/测试库名不得与 app_perf 冲突。
    """
    from urllib.parse import urlparse

    from app.core.config import settings

    if settings.ENVIRONMENT != "local":
        raise SystemExit(
            f"仅允许 ENVIRONMENT=local 运行（当前 {settings.ENVIRONMENT}）"
        )
    admin_uri, _ = _perf_uris()
    host = urlparse(admin_uri).hostname or ""
    if host not in _LOCAL_HOSTS:
        raise SystemExit(f"目标实例不是本机（{host}），拒绝运行")
    for name in (settings.POSTGRES_DB, settings.POSTGRES_DB_TEST):
        if name == PERF_DB_NAME:
            raise SystemExit(f"应用库/测试库名与 {PERF_DB_NAME} 冲突，拒绝运行")


def _prepare_database(create_engine_fn=None):
    """创建本次专用的 app_perf 库。同名既有库一律拒绝——绝不无提示强删。

    返回 (engine, created)；拒绝路径直接 SystemExit，清理只针对本次
    创建的资源（调用方 finally 中执行）。create_engine_fn 可注入以捕获
    DDL（测试用，不实际连库）。
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    if create_engine_fn is None:
        create_engine_fn = create_engine
    admin_uri, perf_uri = _perf_uris()
    admin = create_engine_fn(
        admin_uri, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": PERF_DB_NAME},
            ).scalar()
            if exists:
                raise SystemExit(
                    f"数据库 {PERF_DB_NAME} 已存在：请先人工确认并删除"
                    f"（psql -c 'DROP DATABASE {PERF_DB_NAME}'）再运行，"
                    "本脚本不会无提示强删既有库"
                )
            conn.execute(text(f'CREATE DATABASE "{PERF_DB_NAME}"'))
    finally:
        admin.dispose()
    return create_engine_fn(perf_uri), True


class QueryCounter:
    """统计 SELECT 次数与返回行数（sqlalchemy 事件监听）。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.selects = 0
        self.rows = 0

    def __enter__(self):
        from sqlalchemy import event

        def _before(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                self.selects += 1

        def _after(_conn, cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                self.rows += cursor.rowcount if cursor.rowcount > 0 else 0

        event.listen(self.engine, "before_cursor_execute", _before)
        event.listen(self.engine, "after_cursor_execute", _after)
        self._remove = lambda: (
            event.remove(self.engine, "before_cursor_execute", _before),
            event.remove(self.engine, "after_cursor_execute", _after),
        )
        return self

    def __exit__(self, *exc):
        self._remove()


def _seed(engine, students: int, old_done: int, pending: int, books: int):
    """合成数据：课堂+学生+词汇任务作答 + 学期量旧 done + 词库。"""
    from sqlmodel import Session, SQLModel

    from app.models import (
        Attempt,
        AttemptStatus,
        Classroom,
        Student,
        Tenant,
        User,
        VocabularyAnswer,
        VocabularyAssignment,
        VocabularyAssignmentTarget,
        VocabularyBook,
        VocabularySession,
        VocabularyWord,
    )
    from app.models.base import DEFAULT_TENANT_ID

    SQLModel.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        # 多租户地基（B1）之后 user.tenant_id 有 FK 指向 tenant 表。模型侧的
        # ORM 默认值是 DEFAULT_TENANT_ID，所以先把这条默认租户落库，否则
        # 第一条 insert 就撞 user_tenant_id_fkey。
        session.add(
            Tenant(
                id=DEFAULT_TENANT_ID,
                slug="perf",
                name_zh="性能基线压测租户",
            )
        )
        session.flush()
        teacher = User(
            email="perf-teacher@test.com",
            hashed_password="x",
            is_superuser=True,
        )
        session.add(teacher)
        session.flush()
        classroom = Classroom(
            code="PERF01", name="perf", class_size=students, owner_id=teacher.id
        )
        session.add(classroom)
        session.flush()

        words = [
            VocabularyWord(headword=f"w{i:03d}", meaning_zh=f"词{i}") for i in range(10)
        ]
        session.add_all(words)
        session.flush()
        book = VocabularyBook(title="perf", scope="public", owner_id=teacher.id)
        session.add(book)
        # 其它教师的班级词库：对本教师不可见（测量 SQL 可见性过滤）
        other_teachers = [
            User(email=f"perf-other-{i:02d}@test.com", hashed_password="x")
            for i in range(10)
        ]
        session.add_all(other_teachers)
        session.flush()
        for i in range(books - 1):
            session.add(
                VocabularyBook(
                    title=f"别的老师的词库{i:03d}",
                    scope="classroom",
                    owner_id=other_teachers[i % len(other_teachers)].id,
                )
            )

        snapshot = [
            {"word_id": str(w.id), "headword": w.headword, "meaning_zh": w.meaning_zh}
            for w in words
        ]
        assignment = VocabularyAssignment(
            classroom_id=classroom.id,
            title="perf 任务",
            mode="practice",
            prompt_types=["meaning"],
            snapshot_items=snapshot,
            status="published",
        )
        session.add(assignment)
        session.flush()

        for i in range(students):
            user = User(
                email=f"perf-stu-{i:03d}@test.com",
                hashed_password="x",
                role="student",
            )
            session.add(user)
            session.flush()
            student = Student(
                classroom_id=classroom.id, user_id=user.id, display_name=f"学生{i}"
            )
            session.add(student)
            session.flush()
            session.add(
                VocabularyAssignmentTarget(
                    assignment_id=assignment.id, student_id=student.id
                )
            )
            vs = VocabularySession(
                classroom_id=classroom.id,
                student_id=student.id,
                assignment_id=assignment.id,
                kind="task",
                mode="practice",
                round_no=1,
                status="submitted",
                submitted_at=now,
            )
            session.add(vs)
            session.flush()
            for idx, w in enumerate(words):
                session.add(
                    VocabularyAnswer(
                        session_id=vs.id,
                        item_index=idx,
                        attempt_no=1,
                        prompt_type="meaning",
                        answer_raw=f"w{idx:03d}" if idx % 3 else "wrong",
                        answer_normalized=f"w{idx:03d}" if idx % 3 else "wrong",
                        is_correct=bool(idx % 3),
                        word_id=w.id,
                        headword=w.headword,
                        meaning_zh=w.meaning_zh,
                        answered_at=now,
                    )
                )

        # 学期量旧 done（rubric 空：mock 引擎或未开 rubric 的历史行）
        old = now - timedelta(days=30)
        for i in range(old_done):
            session.add(
                Attempt(
                    item_type="question",
                    item_id=uuid.UUID(int=i),
                    audio_path=f"/perf/{i}.webm",
                    duration_s=5.0,
                    status=AttemptStatus.DONE,
                    created_at=old,
                )
            )
        # 少量挂起详情（刚进入 rubric 不久，不应被关闭）
        for i in range(pending):
            session.add(
                Attempt(
                    item_type="question",
                    item_id=uuid.UUID(int=old_done + i),
                    audio_path=f"/perf/p{i}.webm",
                    duration_s=5.0,
                    status=AttemptStatus.DONE,
                    created_at=old,
                    transcript="hello",
                    rubric={
                        "status": "pending",
                        "pending_since": now.isoformat(),
                    },
                )
            )
        session.commit()
        return classroom.id


# ── 查询数基线（回归守卫）──────────────────────────────────────────────
# SELECT 次数是确定性指标：同一份合成数据、同一版代码必然相同，不受 runner
# 快慢影响，所以适合做硬门禁。2026-11-12 在默认规模（40 学生 / 10000 旧
# done / 5 pending / 200 词库）实测得到下表。任何改动让热路径的 SELECT 跳升
# （典型是新增 N+1 循环：40 学生变 40 次查询）都会在这里立刻变红。
# 行加载只设宽松上限：合成数据的分布会随模型演进小幅浮动，卡太死是噪音。
QUERY_BASELINE: dict[str, tuple[int, int]] = {
    "sweep_orphans 候选": (3, 5),
    "list_books(管理员)": (2, 1),
    "list_books(普通教师)": (2, 21),
    "teacher_assignment_rows": (4, 481),
    "wrong_word_items (today count)": (1, 10),
}
ROW_SLACK = 1.2

_RESULTS: list[tuple[str, int, int]] = []


def _report(name: str, counter: QueryCounter, seconds: float, note: str = "") -> None:
    _RESULTS.append((name, counter.selects, counter.rows))
    print(
        f"| {name} | {counter.selects} 次 SELECT | 约 {counter.rows} 行加载 "
        f"| {seconds * 1000:.1f} ms | {note} |"
    )


def _check_baseline() -> int:
    """比对实测与基线。SELECT 超基线即失败；行加载超宽松上限才失败。

    耗时不做断言：runner 快慢、邻居负载都会影响它，卡时间只会训练人忽略红灯。
    """
    failures: list[str] = []
    measured = {name for name, _s, _r in _RESULTS}
    for name, selects, rows in _RESULTS:
        expect = QUERY_BASELINE.get(name)
        if expect is None:
            failures.append(f"{name}：基线未登记该项（新增测量项需同步补基线）")
            continue
        base_selects, base_rows = expect
        if selects > base_selects:
            failures.append(
                f"{name}：SELECT {selects} > 基线 {base_selects}（疑似 N+1）"
            )
        if rows > int(base_rows * ROW_SLACK) + 1:
            failures.append(f"{name}：行加载 {rows} > 基线 {base_rows} 的宽松上限")
    for name in QUERY_BASELINE:
        if name not in measured:
            failures.append(f"{name}：基线登记了但本次没测到（测量项被删或改名）")
    if failures:
        print("\n❌ 性能回归：", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("\n✅ 查询数与基线一致，行加载在上限内")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", type=int, default=40)
    parser.add_argument("--old-done", type=int, default=10000)
    parser.add_argument("--pending", type=int, default=5)
    parser.add_argument("--books", type=int, default=200)
    parser.add_argument(
        "--keep-db", action="store_true", help="保留本次创建的 app_perf 便于排查"
    )
    parser.add_argument(
        "--assert-baseline",
        action="store_true",
        help="跑完后比对查询数基线，超出则以退出码 1 失败（CI 用）",
    )
    args = parser.parse_args()

    # 安全闸（返修R02）：local 环境 + 本机实例 + 库名不冲突；
    # 同名既有库拒绝——绝不无提示强删
    _refuse_unsafe_target()
    engine, created = _prepare_database()

    from sqlmodel import Session

    from app.core.db import set_engine
    from app.scoring import worker

    set_engine(engine)
    classroom_id = _seed(engine, args.students, args.old_done, args.pending, args.books)

    from app.services import vocabulary as vocab_service

    print(
        f"合成规模：{args.students} 学生 / {args.old_done} 旧 done / "
        f"{args.pending} pending / {args.books} 词库\n"
    )

    # 禁止清扫真实投递（只测查询路径）
    import app.scoring.worker as worker_mod

    worker_mod.submit_attempt_scoring = lambda attempt_id: None

    print("| 测量项 | SELECT | 行加载 | 耗时 | 备注 |")
    print("|---|---|---|---|---|")

    try:
        with Session(engine) as session:
            with QueryCounter(engine) as c:
                start = time.perf_counter()
                worker.sweep_orphans(session)
                _report(
                    "sweep_orphans 候选",
                    c,
                    time.perf_counter() - start,
                    f"旧 done={args.old_done}, pending={args.pending}",
                )

        with Session(engine) as session:
            from sqlmodel import select as _select

            from app.api.routes.vocabulary_books import list_books
            from app.models import User

            teacher = session.exec(
                _select(User).where(User.email == "perf-teacher@test.com")
            ).first()
            assert teacher is not None
            with QueryCounter(engine) as c:
                start = time.perf_counter()
                books = list_books(session, teacher)
                _report(
                    "list_books(管理员)",
                    c,
                    time.perf_counter() - start,
                    f"可见 {len(books)}/{args.books} 本",
                )
            other = session.exec(
                _select(User).where(User.email == "perf-other-00@test.com")
            ).first()
            assert other is not None
            with QueryCounter(engine) as c:
                start = time.perf_counter()
                books = list_books(session, other)
                _report(
                    "list_books(普通教师)",
                    c,
                    time.perf_counter() - start,
                    f"可见 {len(books)}/{args.books} 本（SQL 过滤）",
                )

        with Session(engine) as session:
            with QueryCounter(engine) as c:
                start = time.perf_counter()
                rows = vocab_service.teacher_assignment_rows(session, classroom_id)
                _report(
                    "teacher_assignment_rows",
                    c,
                    time.perf_counter() - start,
                    f"{args.students} 学生全历史（当前 1 任务，{len(rows)} 行）",
                )

        with Session(engine) as session:
            from sqlmodel import select as _select2

            from app.models import Student as _Student

            stu = session.exec(_select2(_Student).limit(1)).first()
            assert stu is not None
            with QueryCounter(engine) as c:
                start = time.perf_counter()
                wrong = vocab_service.wrong_word_items(session, stu.id)
                _report(
                    "wrong_word_items (today count)",
                    c,
                    time.perf_counter() - start,
                    f"错词 {len(wrong)} 个",
                )
    finally:
        set_engine(None)
        engine.dispose()
        # 清理只针对本次创建的资源；崩溃/中断也不留危险状态
        if created and not args.keep_db:
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool

            admin_uri, _ = _perf_uris()
            admin = create_engine(
                admin_uri, isolation_level="AUTOCOMMIT", poolclass=NullPool
            )
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE "{PERF_DB_NAME}" WITH (FORCE)'))
            admin.dispose()
    return _check_baseline() if args.assert_baseline else 0


if __name__ == "__main__":
    raise SystemExit(main())
