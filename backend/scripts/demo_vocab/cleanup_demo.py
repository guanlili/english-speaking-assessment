#!/usr/bin/env python3
"""本地演示词汇数据（demo 命名空间）一键清理脚本。

安全边界（硬要求）：
- 只允许连接本地开发库：host 必须是 ``localhost / 127.0.0.1``，库名必须是
  本地开发库 ``app``；``ENVIRONMENT=production`` 或远程 host 直接退出非 0。
  没有任何 ``--allow-remote`` 绕过开关。
- 只删除固定 demo 命名空间内的对象：
  - 租户 slug ``vocabdemo``；
  - 账号邮箱前缀 ``vocabdemo.``（``vocabdemo.*@example.com``）；
  - 课堂码 ``VOCDEMO1`` / ``VOCDEMO2``；
  - 词库 / 任务标题前缀 ``[DEMO]``；
  - 该租户名下的词、版本快照、授权审计、作答、FSRS 状态、PK、农场、徽章。
- 不按 ``source_type=demo`` 泛删，避免误删其他人的演示数据。
- 删除前先做外部引用护栏：若已有非 demo 数据引用将要删除的对象，停止并报错，
  不做级联误删。

用法（在 ``backend/`` 目录下）：

.. code-block:: bash

    POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
        .venv/bin/python scripts/demo_vocab/cleanup_demo.py
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Mapping
from urllib.parse import urlparse

from sqlalchemy import create_engine, delete
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Classroom,
    ClassroomTeacher,
    Student,
    StudentBadge,
    Tenant,
    TenantModule,
    User,
    VocabFarmPlot,
    VocabPkAnswer,
    VocabPkLobby,
    VocabPkMatch,
    VocabPkPlayer,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularyBook,
    VocabularyBookItem,
    VocabularyBookVersion,
    VocabularyContentReviewAudit,
    VocabularyLicenseAudit,
    VocabularyReviewState,
    VocabularySession,
    VocabularyWord,
)

# ── 固定 demo 命名空间（与 seed_demo.py 同口径，禁止放宽）─────────────────
TENANT_SLUG = "vocabdemo"
TEACHER_EMAIL = "vocabdemo.teacher@example.com"
STUDENT_EMAIL_PREFIX = "vocabdemo.s"
CLASSROOM_CODES = ("VOCDEMO1", "VOCDEMO2")
TITLE_PREFIX = "[DEMO]"

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
ALLOWED_DB_NAMES = {"app"}


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


def _assert_local_uri(uri_str: str) -> None:
    """校验 SQLAlchemy URL 指向本地开发库；不满足直接退出非 0。"""
    if settings.ENVIRONMENT == "production":
        _fail("ENVIRONMENT=production，拒绝在生产库执行 demo 清理。")
    uri = urlparse(uri_str)
    host = uri.hostname or ""
    if host not in ALLOWED_HOSTS:
        _fail(f"拒绝连接非本地 host: {host}（仅允许 localhost / 127.0.0.1）。")
    db_name = (uri.path or "").lstrip("/")
    if db_name not in ALLOWED_DB_NAMES:
        _fail(f"拒绝操作非本地开发库: {db_name}（仅允许 {sorted(ALLOWED_DB_NAMES)}）。")


def safe_engine():
    """按实际 SQLAlchemy URL 做本地库守卫；非本地环境直接退出。"""
    uri_str = str(settings.SQLALCHEMY_ADMIN_DATABASE_URI)
    _assert_local_uri(uri_str)
    return create_engine(uri_str)


def _collect(session: Session) -> dict[str, set[uuid.UUID]]:
    """收集 demo 命名空间内全部对象 id；租户不存在时返回空集合。"""
    tenant = session.exec(select(Tenant).where(Tenant.slug == TENANT_SLUG)).first()
    ids: dict[str, set[uuid.UUID]] = {
        "tenant": set(),
        "users": set(),
        "classrooms": set(),
        "students": set(),
        "books": set(),
        "words": set(),
        "assignments": set(),
        "sessions": set(),
        "lobbies": set(),
        "matches": set(),
        "players": set(),
    }
    if tenant is None:
        return ids
    ids["tenant"].add(tenant.id)

    ids["users"] = {
        row.id
        for row in session.exec(select(User).where(User.tenant_id == tenant.id)).all()
    }
    ids["classrooms"] = {
        row.id
        for row in session.exec(
            select(Classroom).where(Classroom.tenant_id == tenant.id)
        ).all()
    }
    ids["students"] = {
        row.id
        for row in session.exec(
            select(Student).where(Student.classroom_id.in_(ids["classrooms"]))
        ).all()
    }
    ids["books"] = {
        row.id
        for row in session.exec(
            select(VocabularyBook).where(VocabularyBook.tenant_id == tenant.id)
        ).all()
    }
    ids["words"] = {
        row.id
        for row in session.exec(
            select(VocabularyWord).where(VocabularyWord.tenant_id == tenant.id)
        ).all()
    }
    # 注意：assignment 表的 ORM 字段 source_book_ids 在本地库可能尚未落地（C 后端
    # 迁移未到），只查 id 列，避免 ORM 实体查询带出不存在的列。
    ids["assignments"] = {
        row[0]
        for row in session.execute(
            select(VocabularyAssignment.id).where(
                VocabularyAssignment.classroom_id.in_(ids["classrooms"])
            )
        ).all()
    }
    ids["sessions"] = {
        row.id
        for row in session.exec(
            select(VocabularySession).where(
                VocabularySession.classroom_id.in_(ids["classrooms"])
            )
        ).all()
    }
    ids["lobbies"] = {
        row.id
        for row in session.exec(
            select(VocabPkLobby).where(VocabPkLobby.classroom_id.in_(ids["classrooms"]))
        ).all()
    }
    ids["matches"] = {
        row.id
        for row in session.exec(
            select(VocabPkMatch).where(VocabPkMatch.lobby_id.in_(ids["lobbies"]))
        ).all()
    }
    ids["players"] = {
        row.id
        for row in session.exec(
            select(VocabPkPlayer).where(VocabPkPlayer.lobby_id.in_(ids["lobbies"]))
        ).all()
    }
    return ids


def _guard(session: Session, ids: Mapping[str, set[uuid.UUID]]) -> list[str]:
    """外部引用护栏：非 demo 数据引用将删对象时返回冲突说明。"""
    violations: list[str] = []
    if not ids["tenant"]:
        return violations

    # 其他词库收录了 demo 词条
    external_items = session.exec(
        select(VocabularyBookItem).where(
            VocabularyBookItem.word_id.in_(ids["words"]),
            VocabularyBookItem.book_id.notin_(ids["books"]),
        )
    ).all()
    if external_items:
        violations.append(
            f"有 {len(external_items)} 条非 demo 词库条目引用 demo 词条，拒绝删除。"
        )

    # 其他任务的目标名单包含 demo 学生
    external_targets = session.exec(
        select(VocabularyAssignmentTarget).where(
            VocabularyAssignmentTarget.student_id.in_(ids["students"]),
            VocabularyAssignmentTarget.assignment_id.notin_(ids["assignments"]),
        )
    ).all()
    if external_targets:
        violations.append(
            f"有 {len(external_targets)} 条非 demo 任务名单引用 demo 学生，拒绝删除。"
        )

    # 其他任务/自主轮次挂着 demo 学生或 demo 词库
    external_sessions = session.exec(
        select(VocabularySession).where(
            VocabularySession.student_id.in_(ids["students"]),
            VocabularySession.assignment_id.is_not(None),
            VocabularySession.assignment_id.notin_(ids["assignments"]),
        )
    ).all()
    if external_sessions:
        violations.append(
            f"有 {len(external_sessions)} 条非 demo 任务会话引用 demo 学生，拒绝删除。"
        )
    external_self = session.exec(
        select(VocabularySession).where(
            VocabularySession.source_book_id.is_not(None),
            VocabularySession.source_book_id.notin_(ids["books"]),
        )
    ).all()
    # 注：上面这条只作存在性复核；demo 自主轮次本就随课堂一并清理。
    if external_self:
        external_self_demo = [
            s for s in external_self if s.student_id in ids["students"]
        ]
        if external_self_demo:
            violations.append(
                f"有 {len(external_self_demo)} 条 demo 学生自主轮次挂非 demo 词库，拒绝删除。"
            )

    # 非 demo 账号的 FSRS 状态引用 demo 词条
    external_states = session.exec(
        select(VocabularyReviewState).where(
            VocabularyReviewState.word_id.in_(ids["words"]),
            VocabularyReviewState.user_id.notin_(ids["users"]),
        )
    ).all()
    if external_states:
        violations.append(
            f"有 {len(external_states)} 条非 demo 账号复习状态引用 demo 词条，拒绝删除。"
        )

    # 其他大厅/对局包含 demo 学生
    external_players = session.exec(
        select(VocabPkPlayer).where(
            VocabPkPlayer.student_id.in_(ids["students"]),
            VocabPkPlayer.lobby_id.notin_(ids["lobbies"]),
        )
    ).all()
    if external_players:
        violations.append(
            f"有 {len(external_players)} 条非 demo PK 记录引用 demo 学生，拒绝删除。"
        )
    return violations


def _delete_ordered(
    session: Session, ids: Mapping[str, set[uuid.UUID]]
) -> dict[str, int]:
    """按外键安全顺序删除 demo 命名空间对象，返回各类删除计数。"""
    counts: dict[str, int] = {}

    def _bulk(model, where_clause, label: str) -> None:
        result = session.execute(delete(model).where(where_clause))
        counts[label] = int(result.rowcount or 0)

    if not ids["tenant"]:
        return counts

    tenant_id = next(iter(ids["tenant"]))
    _bulk(
        VocabPkAnswer,
        VocabPkAnswer.match_id.in_(ids["matches"]),
        "vocab_pk_answer",
    )
    _bulk(
        VocabPkPlayer,
        VocabPkPlayer.lobby_id.in_(ids["lobbies"]),
        "vocab_pk_player",
    )
    _bulk(
        VocabPkMatch,
        VocabPkMatch.lobby_id.in_(ids["lobbies"]),
        "vocab_pk_match",
    )
    _bulk(
        VocabPkLobby,
        VocabPkLobby.classroom_id.in_(ids["classrooms"]),
        "vocab_pk_lobby",
    )
    _bulk(
        VocabularyAnswer,
        VocabularyAnswer.session_id.in_(ids["sessions"]),
        "vocabulary_answer",
    )
    _bulk(
        VocabularySession,
        VocabularySession.classroom_id.in_(ids["classrooms"]),
        "vocabulary_session",
    )
    _bulk(
        VocabularyAssignmentTarget,
        VocabularyAssignmentTarget.assignment_id.in_(ids["assignments"]),
        "vocabulary_assignment_target",
    )
    _bulk(
        VocabularyAssignment,
        VocabularyAssignment.classroom_id.in_(ids["classrooms"]),
        "vocabulary_assignment",
    )
    _bulk(
        VocabularyReviewState,
        VocabularyReviewState.user_id.in_(ids["users"]),
        "vocabulary_review_state",
    )
    _bulk(
        StudentBadge,
        StudentBadge.student_id.in_(ids["students"]),
        "student_badge",
    )
    _bulk(
        VocabFarmPlot,
        VocabFarmPlot.user_id.in_(ids["users"]),
        "vocab_farm_plot",
    )
    _bulk(
        VocabularyBookItem,
        VocabularyBookItem.book_id.in_(ids["books"]),
        "vocabulary_book_item",
    )
    _bulk(
        VocabularyLicenseAudit,
        VocabularyLicenseAudit.book_id.in_(ids["books"])
        | VocabularyLicenseAudit.word_id.in_(ids["words"]),
        "vocabulary_license_audit",
    )
    _bulk(
        VocabularyContentReviewAudit,
        VocabularyContentReviewAudit.word_id.in_(ids["words"]),
        "vocabulary_content_review_audit",
    )
    _bulk(
        VocabularyBookVersion,
        VocabularyBookVersion.book_id.in_(ids["books"]),
        "vocabulary_book_version",
    )
    _bulk(
        VocabularyWord,
        VocabularyWord.id.in_(ids["words"]),
        "vocabulary_word",
    )
    _bulk(
        VocabularyBook,
        VocabularyBook.id.in_(ids["books"]),
        "vocabulary_book",
    )
    _bulk(
        Student,
        Student.classroom_id.in_(ids["classrooms"]),
        "student",
    )
    _bulk(
        ClassroomTeacher,
        ClassroomTeacher.classroom_id.in_(ids["classrooms"]),
        "classroom_teacher",
    )
    _bulk(
        Classroom,
        Classroom.id.in_(ids["classrooms"]),
        "classroom",
    )
    _bulk(
        TenantModule,
        TenantModule.tenant_id == tenant_id,
        "tenant_module",
    )
    _bulk(User, User.tenant_id == tenant_id, "user")
    _bulk(Tenant, Tenant.id == tenant_id, "tenant")
    return counts


def reset_demo_namespace(session: Session, *, commit: bool = True) -> dict[str, int]:
    """供 seed 脚本复用：先护栏、再清空 demo 命名空间。返回删除计数。"""
    ids = _collect(session)
    violations = _guard(session, ids)
    if violations:
        for v in violations:
            print(f"GUARD: {v}", file=sys.stderr)
        session.rollback()
        sys.exit(3)
    if not ids["tenant"]:
        return {}
    counts = _delete_ordered(session, ids)
    if commit:
        session.commit()
    return counts


def main() -> None:
    engine = safe_engine()
    with Session(engine) as session:
        ids = _collect(session)
        if not ids["tenant"]:
            print("未发现 demo 命名空间（租户 vocabdemo），无需清理。")
            return

        violations = _guard(session, ids)
        if violations:
            for v in violations:
                print(f"GUARD: {v}", file=sys.stderr)
            session.rollback()
            sys.exit(3)

        print("即将删除以下 demo 命名空间对象（删除前计数）：")
        preview = {
            "tenant": len(ids["tenant"]),
            "user": len(ids["users"]),
            "classroom": len(ids["classrooms"]),
            "student": len(ids["students"]),
            "vocabulary_book": len(ids["books"]),
            "vocabulary_word": len(ids["words"]),
            "vocabulary_assignment": len(ids["assignments"]),
            "vocabulary_session": len(ids["sessions"]),
            "vocab_pk_lobby": len(ids["lobbies"]),
            "vocab_pk_match": len(ids["matches"]),
            "vocab_pk_player": len(ids["players"]),
        }
        for label, count in preview.items():
            print(f"  - {label}: {count}")

        counts = _delete_ordered(session, ids)
        session.commit()

        print("\n删除完成，各类对象计数：")
        for label, count in counts.items():
            print(f"  - {label}: {count}")

        # 复核：demo 命名空间计数应全部为 0
        leftover = _collect(session)
        print("\n清理后复核：")
        for label, bucket in (
            ("tenant", "tenant"),
            ("user", "users"),
            ("classroom", "classrooms"),
            ("student", "students"),
            ("vocabulary_book", "books"),
            ("vocabulary_word", "words"),
            ("vocabulary_assignment", "assignments"),
            ("vocabulary_session", "sessions"),
            ("vocab_pk_lobby", "lobbies"),
            ("vocab_pk_match", "matches"),
            ("vocab_pk_player", "players"),
        ):
            print(f"  - {label}: {len(leftover[bucket])}")


if __name__ == "__main__":
    main()
