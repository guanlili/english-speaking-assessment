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
"""

import argparse
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PERF_DB_NAME = "app_perf"


def _build_engine():
    """从应用测试 DSN 派生凭据（同一实例），库固定为 app_perf。"""
    from urllib.parse import urlparse, urlunparse

    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

    parsed = urlparse(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    admin_uri = urlunparse(parsed._replace(path=f"/{PERF_DB_NAME}")).replace(
        f"/{PERF_DB_NAME}", "/postgres"
    )
    perf_uri = urlunparse(parsed._replace(path=f"/{PERF_DB_NAME}"))
    admin = create_engine(admin_uri, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{PERF_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{PERF_DB_NAME}"'))
    admin.dispose()
    return create_engine(perf_uri)


class QueryCounter:
    """统计 SELECT 次数与返回行数（sqlalchemy 事件监听）。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.selects = 0
        self.rows = 0

    def __enter__(self):
        from sqlalchemy import event

        def _before(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                self.selects += 1

        def _after(conn, cursor, statement, parameters, context, executemany):
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
    from sqlmodel import SQLModel, Session

    from app.models import (
        Attempt,
        AttemptStatus,
        Classroom,
        Student,
        User,
        VocabularyAnswer,
        VocabularyAssignment,
        VocabularyAssignmentTarget,
        VocabularyBook,
        VocabularySession,
        VocabularyWord,
    )

    SQLModel.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
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
            User(
                email=f"perf-other-{i:02d}@test.com", hashed_password="x"
            )
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


def _report(name: str, counter: QueryCounter, seconds: float, note: str = "") -> None:
    print(
        f"| {name} | {counter.selects} 次 SELECT | 约 {counter.rows} 行加载 "
        f"| {seconds * 1000:.1f} ms | {note} |"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", type=int, default=40)
    parser.add_argument("--old-done", type=int, default=10000)
    parser.add_argument("--pending", type=int, default=5)
    parser.add_argument("--books", type=int, default=200)
    parser.add_argument("--keep-db", action="store_true", help="保留 app_perf 便于排查")
    args = parser.parse_args()

    import os

    # 安全：只连独立的 app_perf 合成库（_build_engine 硬编码建/删该库），
    # 开发库 app 与测试库 app_test 都不会被触碰
    server = os.environ.get("POSTGRES_SERVER", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5433")

    engine = _build_engine()
    from sqlmodel import Session

    from app.core.db import set_engine
    from app.scoring import worker

    set_engine(engine)
    classroom_id = _seed(
        engine, args.students, args.old_done, args.pending, args.books
    )

    from app.services import vocabulary as vocab_service

    print(f"合成规模：{args.students} 学生 / {args.old_done} 旧 done / "
          f"{args.pending} pending / {args.books} 词库\n")

    # 禁止清扫真实投递（只测查询路径）
    import app.scoring.worker as worker_mod

    worker_mod.submit_attempt_scoring = lambda attempt_id: None

    print("| 测量项 | SELECT | 行加载 | 耗时 | 备注 |")
    print("|---|---|---|---|---|")

    with Session(engine) as session:
        with QueryCounter(engine) as c:
            start = time.perf_counter()
            worker.sweep_orphans(session)
            _report("sweep_orphans 候选", c, time.perf_counter() - start,
                    f"旧 done={args.old_done}, pending={args.pending}")

    with Session(engine) as session:
        from sqlmodel import select as _select

        from app.api.routes.vocabulary import list_books
        from app.models import User

        teacher = session.exec(
            _select(User).where(User.email == "perf-teacher@test.com")
        ).first()
        assert teacher is not None
        with QueryCounter(engine) as c:
            start = time.perf_counter()
            books = list_books(session, teacher)
            _report("list_books(管理员)", c, time.perf_counter() - start,
                    f"可见 {len(books)}/{args.books} 本")
        other = session.exec(
            _select(User).where(User.email == "perf-other-00@test.com")
        ).first()
        assert other is not None
        with QueryCounter(engine) as c:
            start = time.perf_counter()
            books = list_books(session, other)
            _report("list_books(普通教师)", c, time.perf_counter() - start,
                    f"可见 {len(books)}/{args.books} 本（SQL 过滤）")

    with Session(engine) as session:
        with QueryCounter(engine) as c:
            start = time.perf_counter()
            rows = vocab_service.teacher_assignment_rows(session, classroom_id)
            _report("teacher_assignment_rows", c, time.perf_counter() - start,
                    f"{args.students} 学生全历史（当前 1 任务）")

    with Session(engine) as session:
        from sqlmodel import select as _select2

        from app.models import Student as _Student

        stu = session.exec(_select2(_Student).limit(1)).first()
        with QueryCounter(engine) as c:
            start = time.perf_counter()
            wrong = vocab_service.wrong_word_items(session, stu.id)
            _report("wrong_word_items (today count)", c,
                    time.perf_counter() - start, f"错词 {len(wrong)} 个")

    set_engine(None)
    if not args.keep_db:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool
        from urllib.parse import urlparse, urlunparse

        from app.core.config import settings as _settings

        parsed = urlparse(str(_settings.SQLALCHEMY_DATABASE_TEST_URI))
        admin_uri = urlunparse(parsed._replace(path="/postgres"))
        admin = create_engine(
            admin_uri, isolation_level="AUTOCOMMIT", poolclass=NullPool
        )
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{PERF_DB_NAME}" WITH (FORCE)'))
        admin.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
