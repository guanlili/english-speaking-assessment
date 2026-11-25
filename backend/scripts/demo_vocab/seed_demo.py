#!/usr/bin/env python3
"""本地演示词汇数据种子脚本（demo 命名空间，幂等可重跑）。

只面向本地开发库造一套可演示、可一键清理的 mock 词汇数据，供后续 A/B/C
取证使用；**不接入生产、不生成迁移、不改应用代码**。

安全边界（硬要求，与 ``cleanup_demo.py`` 同口径）：
- 启动时解析实际 SQLAlchemy URL：host 必须是 ``localhost / 127.0.0.1``，库名
  必须是本地开发库 ``app``；``ENVIRONMENT=production`` 或远程 host 直接退出
  非 0，没有 ``--allow-remote`` 绕过开关。
- 全部对象落在固定 demo 命名空间：租户 ``vocabdemo``、账号
  ``vocabdemo.*@example.com``、课堂码 ``VOCDEMO1 / VOCDEMO2``、词库/任务标题
  前缀 ``[DEMO]``。
- 默认先清理旧 demo 命名空间再种，保证幂等；清理规则见 ``cleanup_demo.py``。

数据规模：
- 五级词库 KET / PET / ACADEMIC / CET4 / IELTS_TOEFL 各 44 词，共 220，
  全部来自 ``words.json``；KET 词库走 v1 36 词 → v2 40 词（改释义/例句）→
  v3 44 词三个真实版本快照；
- 2 个授权演示词库（有效期内教材库 20 词 2 版本、已过期授权库 10 词），
  配套 3 条授权审计行；
- 2 间课堂：VOCDEMO1 12 名学生、VOCDEMO2 6 名学生（跨班 404 隔离演示）；
- VOCDEMO1 5 个教师任务，覆盖 meaning / cloze / roots 三种题型，首答正确率
  形成 low / mid / high 分段；部分错题带 attempt_no=2 重试（不计首答统计）；
- 6–10 名学生 × 若干词的 FSRS 复习状态，due_at 分布过去 / 本周 / 未来；
- 2 场已结束 PK（含玩家与作答）、5 个农场地块与 4 枚农场徽章。

用法（在 ``backend/`` 目录下）：

.. code-block:: bash

    POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
        .venv/bin/python scripts/demo_vocab/seed_demo.py

环境变量：

- ``VOCAB_DEMO_PASSWORD``：演示账号口令；未设置时使用固定本地演示口令
  ``Demo2026!``（仅本地 mock，绝不用于生产）。
- ``DEMO_ANCHOR_DATE``：任务发布时间锚点日期（``YYYY-MM-DD``），默认
  ``2026-11-25``。
"""

from __future__ import annotations

import json
import os
import random
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from cleanup_demo import (  # noqa: E402  同目录脚本，脚本目录已在 sys.path
    TENANT_SLUG,
    reset_demo_namespace,
    safe_engine,
)
from sqlalchemy import insert, inspect
from sqlmodel import Session, select

from app.core.security import get_password_hash
from app.core.tenant_context import tenant_scope
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
    VocabularyLicenseAudit,
    VocabularyReviewState,
    VocabularySession,
    VocabularyWord,
)
from app.services import vocab_governance as governance
from app.services import vocabulary as vocab_service
from app.services import vocabulary_prompt_types as prompt_types

# ── 固定 demo 命名空间 ──────────────────────────────────────────────────
TEACHER_EMAIL = "vocabdemo.teacher@example.com"
ADMIN_EMAIL = "vocabdemo.admin@example.com"
STUDENT_EMAIL_PREFIX = "vocabdemo.s"
CLASSROOM_DEMO1 = "VOCDEMO1"
CLASSROOM_DEMO2 = "VOCDEMO2"
DEMO1_STUDENTS = 12
DEMO2_STUDENTS = 6
TITLE_PREFIX = "[DEMO]"

LEVELS = ["KET", "PET", "ACADEMIC", "CET4", "IELTS_TOEFL"]

DEMO_LICENSE_OWNER = "Demo Content Team"
DEMO_LICENSE_REF = "DEMO-ONLY"
DEMO_LICENSE_NOTE = "本地演示数据（demo-only），禁止导入生产环境"

PASSWORD_ENV = "VOCAB_DEMO_PASSWORD"
DEFAULT_DEMO_PASSWORD = "Demo2026!"
ANCHOR_ENV = "DEMO_ANCHOR_DATE"
DEFAULT_ANCHOR = "2026-11-25"

# 任务计划：级别、题型、选词数、距锚点周数（4 → 0，覆盖最近 5 个自然周）
ASSIGNMENT_PLAN = [
    ("KET", ["meaning"], 8, 4),
    ("PET", ["meaning", "cloze"], 8, 3),
    ("ACADEMIC", ["cloze", "roots"], 8, 2),
    ("CET4", ["meaning", "roots"], 8, 1),
    ("IELTS_TOEFL", ["meaning", "cloze"], 10, 0),
]

WORDS_FILE = Path(__file__).resolve().parent / "words.json"


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


def _anchor_date() -> date:
    raw = os.environ.get(ANCHOR_ENV, DEFAULT_ANCHOR)
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        _fail(f"{ANCHOR_ENV} 日期格式应为 YYYY-MM-DD，收到: {raw}")
        raise  # pragma: no cover


def _anchor_dt(
    anchor: date, *, days: int = 0, hour: int = 9, minute: int = 0
) -> datetime:
    return datetime(
        anchor.year, anchor.month, anchor.day, hour, minute, tzinfo=UTC
    ) + timedelta(days=days)


def _load_words() -> dict[str, list[dict[str, object]]]:
    data = json.loads(WORDS_FILE.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, object]]] = {lv: [] for lv in LEVELS}
    for word in data["words"]:
        grouped[word["level"]].append(word)  # type: ignore[index]
    return grouped


def _make_word(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_row: dict[str, object],
    source_type: str,
    legacy_source: str,
    license_owner: str | None,
    license_ref: str | None,
    license_expires_at: datetime | None,
    license_note: str | None,
    reviewer_id: uuid.UUID | None,
) -> VocabularyWord:
    word = VocabularyWord(
        tenant_id=tenant_id,
        headword=str(source_row["headword"]),
        part_of_speech=str(source_row["part_of_speech"]),
        meaning_zh=str(source_row["meaning_zh"]),
        meaning_en=str(source_row["meaning_en"]),
        example_en=str(source_row["example_en"]),
        morphology=list(source_row["morphology"]),  # type: ignore[arg-type]
        status="active",
        source_type=source_type,
        license_owner=license_owner,
        license_ref=license_ref,
        license_expires_at=license_expires_at,
        license_note=license_note,
        source=legacy_source,
        review_status="approved",
        reviewer_id=reviewer_id,
        reviewed_at=datetime.now(UTC),
        review_note="本地演示词条，不用于生产",
        version=1,
    )
    session.add(word)
    session.flush()
    return word


def _attach_items(
    session: Session,
    book: VocabularyBook,
    words: list[VocabularyWord],
    position_start: int = 1,
) -> None:
    for offset, word in enumerate(words):
        session.add(
            VocabularyBookItem(
                tenant_id=book.tenant_id,
                book_id=book.id,
                word_id=word.id,
                position=position_start + offset,
            )
        )
    session.flush()


def ensure_tenant(session: Session) -> Tenant:
    tenant = session.exec(select(Tenant).where(Tenant.slug == TENANT_SLUG)).first()
    if tenant is None:
        tenant = Tenant(
            slug=TENANT_SLUG,
            name_zh="演示学校（DEMO）",
            name_en="Demo School",
            status="active",
            timezone="Asia/Shanghai",
        )
        session.add(tenant)
        session.flush()
    return tenant


def ensure_module(session: Session, tenant: Tenant) -> None:
    existing = session.exec(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant.id,
            TenantModule.module_key == "vocabulary",
        )
    ).first()
    if existing is None:
        session.add(
            TenantModule(
                tenant_id=tenant.id,
                module_key="vocabulary",
                enabled=True,
                grant_type="manual",
            )
        )
        session.flush()


def ensure_teacher(session: Session, tenant: Tenant, pw_hash: str) -> User:
    teacher = session.exec(
        select(User).where(User.tenant_id == tenant.id, User.email == TEACHER_EMAIL)
    ).first()
    if teacher is None:
        teacher = User(
            tenant_id=tenant.id,
            email=TEACHER_EMAIL,
            full_name="演示教师",
            username="vocabdemo.teacher",
            role="teacher",
            is_active=True,
            hashed_password=pw_hash,
            must_change_password=False,
        )
        session.add(teacher)
        session.flush()
    return teacher


def ensure_admin(session: Session, tenant: Tenant, pw_hash: str) -> User:
    """演示校级管理员：供 /admin/vocabbooks 授权/版本管理取证。

    角色 ``school_admin``：词库 CRUD、授权台账、版本历史、审计/CSV 导出等
    校级端点均可访问；口令与教师/学生同一演示口令来源。幂等：重复 seed
    不重复建。
    """
    admin = session.exec(
        select(User).where(User.tenant_id == tenant.id, User.email == ADMIN_EMAIL)
    ).first()
    if admin is None:
        admin = User(
            tenant_id=tenant.id,
            email=ADMIN_EMAIL,
            full_name="演示管理员",
            username="vocabdemo.admin",
            role="school_admin",
            is_active=True,
            hashed_password=pw_hash,
            must_change_password=False,
        )
        session.add(admin)
        session.flush()
    return admin


def ensure_classrooms(
    session: Session, tenant: Tenant, teacher: User
) -> dict[str, Classroom]:
    rooms: dict[str, Classroom] = {}
    specs = [
        (CLASSROOM_DEMO1, "演示一班（DEMO）", DEMO1_STUDENTS, "B1"),
        (CLASSROOM_DEMO2, "演示二班（DEMO）", DEMO2_STUDENTS, "A2"),
    ]
    for code, name, size, grade in specs:
        room = session.exec(select(Classroom).where(Classroom.code == code)).first()
        if room is None:
            room = Classroom(
                code=code,
                tenant_id=tenant.id,
                name=name,
                grade=grade,
                teaching_goal="本地演示课堂，不用于生产",
                class_size=size,
                is_active=True,
                owner_id=teacher.id,
            )
            session.add(room)
            session.flush()
        membership = session.exec(
            select(ClassroomTeacher).where(
                ClassroomTeacher.classroom_id == room.id,
                ClassroomTeacher.user_id == teacher.id,
            )
        ).first()
        if membership is None:
            session.add(
                ClassroomTeacher(
                    classroom_id=room.id,
                    user_id=teacher.id,
                    role="owner",
                    tenant_id=tenant.id,
                    created_by=teacher.id,
                )
            )
        rooms[code] = room
    session.flush()
    return rooms


def ensure_students(
    session: Session,
    tenant: Tenant,
    rooms: dict[str, Classroom],
    pw_hash: str,
) -> dict[str, list[Student]]:
    result: dict[str, list[Student]] = {}
    specs = [(CLASSROOM_DEMO1, DEMO1_STUDENTS), (CLASSROOM_DEMO2, DEMO2_STUDENTS)]
    for code, count in specs:
        room = rooms[code]
        students: list[Student] = []
        for idx in range(1, count + 1):
            email = f"{STUDENT_EMAIL_PREFIX}{idx:02d}@example.com"
            user = session.exec(
                select(User).where(User.tenant_id == tenant.id, User.email == email)
            ).first()
            if user is None:
                user = User(
                    tenant_id=tenant.id,
                    email=email,
                    full_name=f"演示学生{idx:02d}",
                    username=f"vocabdemo.s{idx:02d}",
                    role="student",
                    is_active=True,
                    hashed_password=pw_hash,
                    must_change_password=False,
                )
                session.add(user)
                session.flush()
            student = session.exec(
                select(Student).where(
                    Student.classroom_id == room.id, Student.user_id == user.id
                )
            ).first()
            if student is None:
                student = Student(
                    tenant_id=tenant.id,
                    classroom_id=room.id,
                    user_id=user.id,
                    display_name=f"演示学生{idx:02d}",
                    current_band="B1",
                    xp=0,
                    streak_days=0,
                )
                session.add(student)
                session.flush()
            students.append(student)
        result[code] = students
    return result


def seed_level_books(
    session: Session,
    tenant: Tenant,
    teacher: User,
    grouped: dict[str, list[dict[str, object]]],
) -> dict[str, VocabularyBook]:
    """五级演示词库；KET 走三版演进（36 → 40 → 44）。"""
    books: dict[str, VocabularyBook] = {}

    for level in LEVELS:
        sources = grouped[level]
        book = VocabularyBook(
            tenant_id=tenant.id,
            title=f"{TITLE_PREFIX} {level} 演示词库",
            description="本地演示词库，条目来自 words.json，禁止导入生产",
            scope="public",
            owner_id=teacher.id,
            status="active",
            version=1,
            source_type="demo",
            license_owner=DEMO_LICENSE_OWNER,
            license_ref=DEMO_LICENSE_REF,
            license_note=DEMO_LICENSE_NOTE,
        )
        session.add(book)
        session.flush()

        if level == "KET":
            # v1：36 词
            v1_words = [
                _make_word(
                    session,
                    tenant_id=tenant.id,
                    source_row=sources[i],
                    source_type="demo",
                    legacy_source="demo",
                    license_owner=DEMO_LICENSE_OWNER,
                    license_ref=DEMO_LICENSE_REF,
                    license_expires_at=None,
                    license_note=DEMO_LICENSE_NOTE,
                    reviewer_id=teacher.id,
                )
                for i in range(36)
            ]
            _attach_items(session, book, v1_words)
            governance.capture_version(
                session,
                book,
                actor=teacher,
                action="create",
                summary="v1：收录 36 个 KET 演示词",
            )

            # v2：改首条释义/例句 + 补 4 词（37–40）
            v1_words[0].meaning_zh = f"{v1_words[0].meaning_zh}（演示修订）"
            v1_words[
                0
            ].example_en = (
                "My grandmother keeps apple trees in the small garden behind the house."
            )
            v2_added = [
                _make_word(
                    session,
                    tenant_id=tenant.id,
                    source_row=sources[i],
                    source_type="demo",
                    legacy_source="demo",
                    license_owner=DEMO_LICENSE_OWNER,
                    license_ref=DEMO_LICENSE_REF,
                    license_expires_at=None,
                    license_note=DEMO_LICENSE_NOTE,
                    reviewer_id=teacher.id,
                )
                for i in range(36, 40)
            ]
            _attach_items(session, book, v2_added, position_start=37)
            governance.capture_version(
                session,
                book,
                actor=teacher,
                action="edit_word",
                summary="v2：修订首条释义与例句，补入 4 词（共 40）",
            )

            # v3：补足 44 词（最终版）
            v3_added = [
                _make_word(
                    session,
                    tenant_id=tenant.id,
                    source_row=sources[i],
                    source_type="demo",
                    legacy_source="demo",
                    license_owner=DEMO_LICENSE_OWNER,
                    license_ref=DEMO_LICENSE_REF,
                    license_expires_at=None,
                    license_note=DEMO_LICENSE_NOTE,
                    reviewer_id=teacher.id,
                )
                for i in range(40, 44)
            ]
            _attach_items(session, book, v3_added, position_start=41)
            governance.capture_version(
                session,
                book,
                actor=teacher,
                action="add_words",
                summary="v3：补足 44 词（最终版）",
            )
        else:
            words = [
                _make_word(
                    session,
                    tenant_id=tenant.id,
                    source_row=source,
                    source_type="demo",
                    legacy_source="demo",
                    license_owner=DEMO_LICENSE_OWNER,
                    license_ref=DEMO_LICENSE_REF,
                    license_expires_at=None,
                    license_note=DEMO_LICENSE_NOTE,
                    reviewer_id=teacher.id,
                )
                for source in sources
            ]
            _attach_items(session, book, words)
            governance.capture_version(
                session,
                book,
                actor=teacher,
                action="create",
                summary=f"创建 {level} 演示词库，共 {len(words)} 词",
            )

        books[level] = book
    return books


def seed_license_books(
    session: Session,
    tenant: Tenant,
    teacher: User,
    grouped: dict[str, list[dict[str, object]]],
    anchor: date,
) -> dict[str, VocabularyBook]:
    """授权演示：有效期内教材库（20 词 2 版本）+ 已过期授权库（10 词）。"""
    ket = grouped["KET"]
    books: dict[str, VocabularyBook] = {}

    # ── 有效期内教材词库 ────────────────────────────────────────────────
    textbook = VocabularyBook(
        tenant_id=tenant.id,
        title=f"{TITLE_PREFIX} 授权教材词库",
        description="本地演示：有效期内的教材授权台账样例，非真实教材授权",
        scope="public",
        owner_id=teacher.id,
        status="active",
        version=1,
        source_type="textbook",
        license_owner="演示教材出版社（DEMO）",
        license_ref="DEMO-TEXTBOOK-2026",
        license_expires_at=_anchor_dt(anchor, days=365, hour=0),
        license_note="本地演示授权台账样例：有效期内",
    )
    session.add(textbook)
    session.flush()

    textbook_words = [
        _make_word(
            session,
            tenant_id=tenant.id,
            source_row=ket[i],
            source_type="textbook",
            legacy_source="textbook",
            license_owner="演示教材出版社（DEMO）",
            license_ref="DEMO-TEXTBOOK-2026",
            license_expires_at=_anchor_dt(anchor, days=365, hour=0),
            license_note="本地演示教材授权，非真实版权材料",
            reviewer_id=teacher.id,
        )
        for i in range(20)
    ]
    _attach_items(session, textbook, textbook_words)
    governance.capture_version(
        session,
        textbook,
        actor=teacher,
        action="create",
        summary="v1：收录 20 个教材演示词",
    )

    # v2：修订两条释义
    textbook_words[0].meaning_zh = f"{textbook_words[0].meaning_zh}（教材修订）"
    textbook_words[1].meaning_zh = f"{textbook_words[1].meaning_zh}（教材修订）"
    session.flush()
    governance.capture_version(
        session,
        textbook,
        actor=teacher,
        action="edit_word",
        summary="v2：修订 2 条教材释义",
    )

    # 授权审计 #1：教材库续期备注留痕
    governance.apply_license_update(
        session,
        target=textbook,
        target_type="book",
        book_id=textbook.id,
        word_id=None,
        actor=teacher,
        payload={"license_note": "本地演示授权台账样例：有效期内，续期已留痕"},
        note="演示续期审计（教材库）",
    )
    # 授权审计 #2：单条词条授权引用号留痕
    governance.apply_license_update(
        session,
        target=textbook_words[2],
        target_type="word",
        book_id=textbook.id,
        word_id=textbook_words[2].id,
        actor=teacher,
        payload={"license_ref": "DEMO-TEXTBOOK-WORD-03"},
        note="演示词条授权引用号变更",
    )
    books["textbook"] = textbook

    # ── 已过期授权词库 ─────────────────────────────────────────────────
    expired = VocabularyBook(
        tenant_id=tenant.id,
        title=f"{TITLE_PREFIX} 过期授权词库",
        description="本地演示：已过期授权的词库状态样例",
        scope="public",
        owner_id=teacher.id,
        status="active",
        version=1,
        # 先落中性默认值，授权字段由下方 apply_license_update 写入，
        # 保证审计行有真实 from/to 前后值可查。
        source_type="self_built",
        license_owner=None,
        license_ref=None,
        license_expires_at=None,
        license_note=None,
    )
    session.add(expired)
    session.flush()

    expired_words = [
        _make_word(
            session,
            tenant_id=tenant.id,
            source_row=ket[20 + i],
            source_type="licensed",
            legacy_source="import",
            license_owner="演示授权方（DEMO）",
            license_ref="DEMO-LICENSED-EXPIRED",
            license_expires_at=_anchor_dt(anchor, days=-30, hour=0),
            license_note="已过期演示授权，不用于生产",
            reviewer_id=teacher.id,
        )
        for i in range(10)
    ]
    _attach_items(session, expired, expired_words)
    governance.capture_version(
        session,
        expired,
        actor=teacher,
        action="create",
        summary="创建过期授权演示词库，共 10 词",
    )

    # 授权审计 #3：过期库授权字段落账留痕（from 为空默认值 → to 过期授权）
    governance.apply_license_update(
        session,
        target=expired,
        target_type="book",
        book_id=expired.id,
        word_id=None,
        actor=teacher,
        payload={
            "source_type": "licensed",
            "license_owner": "演示授权方（DEMO）",
            "license_ref": "DEMO-LICENSED-EXPIRED",
            "license_expires_at": _anchor_dt(anchor, days=-30, hour=0),
            "license_note": "已过期演示授权，仅用于演示过期态",
        },
        note="演示过期授权审计",
    )
    books["expired"] = expired
    return books


def _book_words(session: Session, book: VocabularyBook) -> list[VocabularyWord]:
    rows = session.exec(
        select(VocabularyWord)
        .join(VocabularyBookItem, VocabularyBookItem.word_id == VocabularyWord.id)
        .where(VocabularyBookItem.book_id == book.id)
        .order_by(VocabularyBookItem.position)
    ).all()
    return list(rows)


def _build_snapshots(
    words: list[VocabularyWord], prompt_type_list: list[str]
) -> list[dict[str, object]]:
    per_item = prompt_types.plan_item_prompt_types(words, prompt_type_list)
    snapshots = [
        vocab_service.build_word_snapshot(word, types)
        for word, types in zip(words, per_item, strict=True)
    ]
    prompt_types.attach_prompt_payloads(snapshots, words)
    return snapshots


class _AssignmentRef:
    """任务轻量引用：本地库可能缺 source_book_ids 列，不走 ORM 实体回读。"""

    __slots__ = ("id", "snapshot_items", "published_at")

    def __init__(
        self,
        id: uuid.UUID,
        snapshot_items: list[dict[str, object]],
        published_at: datetime,
    ) -> None:
        self.id = id
        self.snapshot_items = snapshot_items
        self.published_at = published_at


def seed_assignments(
    session: Session,
    tenant: Tenant,
    teacher: User,
    room: Classroom,
    students: list[Student],
    level_books: dict[str, VocabularyBook],
    anchor: date,
    *,
    has_source_book_ids: bool,
) -> list[_AssignmentRef]:
    assignments: list[_AssignmentRef] = []
    rng = random.Random(20261125)

    for version_no, (level, prompt_types_, take, week_offset) in enumerate(
        ASSIGNMENT_PLAN, start=1
    ):
        book = level_books[level]
        words = _book_words(session, book)[:take]
        prompt_types.validate_content_availability(words, prompt_types_)
        snapshots = _build_snapshots(words, prompt_types_)
        published_at = _anchor_dt(anchor, days=-7 * week_offset, hour=9)

        data: dict[str, object] = {
            "tenant_id": tenant.id,
            "classroom_id": room.id,
            "created_by": teacher.id,
            "title": f"{TITLE_PREFIX} {level} 周练习（第 {5 - week_offset} 周）",
            "mode": "practice",
            "prompt_types": prompt_types_,
            "snapshot_items": snapshots,
            "version_no": version_no,
            "status": "published",
            "opens_at": published_at,
            "due_at": _anchor_dt(anchor, days=14, hour=23, minute=59),
            "published_at": published_at,
        }
        if has_source_book_ids:
            data["source_book_ids"] = [str(book.id)]
        session.execute(insert(VocabularyAssignment).values(**data))
        session.flush()

        assignment_id = session.execute(
            select(VocabularyAssignment.id).where(
                VocabularyAssignment.classroom_id == room.id,
                VocabularyAssignment.version_no == version_no,
            )
        ).scalar_one()
        assignments.append(
            _AssignmentRef(
                id=assignment_id,
                snapshot_items=snapshots,
                published_at=published_at,
            )
        )

        for student in students:
            session.add(
                VocabularyAssignmentTarget(
                    tenant_id=tenant.id,
                    assignment_id=assignment_id,
                    student_id=student.id,
                )
            )
        session.flush()

    # ── 会话与作答：high / mid / low / 未开始 四档 ─────────────────────
    high = students[0:5]
    mid = students[5:9]
    low = students[9:11]
    none_student = students[11]

    for task_idx, assignment in enumerate(assignments):
        snapshots = list(assignment.snapshot_items or [])
        item_count = len(snapshots)

        def _start(
            assignment: VocabularyAssignment = assignment, task_idx: int = task_idx
        ) -> datetime:
            return (
                assignment.published_at
                + timedelta(hours=1)
                + timedelta(minutes=task_idx * 5)
            )

        def _make_session(
            student: Student,
            status: str,
            answered: int,
            assignment: VocabularyAssignment = assignment,
        ) -> VocabularySession:
            started = _start()
            submitted = (
                started + timedelta(minutes=15 + answered * 2)
                if status == "submitted"
                else None
            )
            session_row = VocabularySession(
                tenant_id=tenant.id,
                classroom_id=room.id,
                student_id=student.id,
                assignment_id=assignment.id,
                kind="task",
                source_book_id=None,
                snapshot_items=None,
                mix_wrong=False,
                mode="practice",
                status=status,
                started_at=started,
                submitted_at=submitted,
                round_no=1,
                tab_switch_count=0,
                end_reason="manual" if status == "submitted" else None,
            )
            session.add(session_row)
            session.flush()
            return session_row

        def _answer(
            session_row: VocabularySession,
            idx: int,
            snapshot: dict[str, object],
            *,
            accuracy: float,
        ) -> None:
            headword = str(snapshot["headword"])
            meaning_zh = str(snapshot["meaning_zh"])
            word_id = uuid.UUID(str(snapshot["word_id"]))
            correct = rng.random() < accuracy
            raw = headword if correct else _typo(headword)
            normalized = vocab_service.normalize_spelling(raw)
            answered_at = _start() + timedelta(
                minutes=idx * 2, seconds=rng.randint(0, 50)
            )

            session.add(
                VocabularyAnswer(
                    tenant_id=tenant.id,
                    session_id=session_row.id,
                    item_index=idx,
                    attempt_no=1,
                    prompt_type=str((snapshot.get("prompt_types") or ["meaning"])[0]),
                    answer_raw=raw,
                    answer_normalized=normalized,
                    is_correct=correct,
                    word_id=word_id,
                    headword=headword,
                    meaning_zh=meaning_zh,
                    answered_at=answered_at,
                    idempotency_key=f"demo-{uuid.uuid4().hex}",
                )
            )
            # 部分错题带 attempt_no=2 重试；重试证据不进首答统计
            if not correct and rng.random() < 0.3:
                session.add(
                    VocabularyAnswer(
                        tenant_id=tenant.id,
                        session_id=session_row.id,
                        item_index=idx,
                        attempt_no=2,
                        prompt_type=str(
                            (snapshot.get("prompt_types") or ["meaning"])[0]
                        ),
                        answer_raw=headword,
                        answer_normalized=vocab_service.normalize_spelling(headword),
                        is_correct=True,
                        word_id=word_id,
                        headword=headword,
                        meaning_zh=meaning_zh,
                        answered_at=answered_at + timedelta(seconds=20),
                        idempotency_key=f"demo-{uuid.uuid4().hex}",
                    )
                )

        for student in high:
            sess = _make_session(student, "submitted", item_count)
            for idx, snapshot in enumerate(snapshots):
                _answer(sess, idx, snapshot, accuracy=0.85)

        for student in mid:
            if task_idx <= 2:
                sess = _make_session(student, "submitted", item_count)
                answered = item_count
            else:
                answered = max(1, (item_count + 1) // 2)
                sess = _make_session(student, "in_progress", answered)
            for idx, snapshot in enumerate(snapshots[:answered]):
                _answer(sess, idx, snapshot, accuracy=0.6)

        for student in low:
            if task_idx <= 1:
                answered = max(1, (item_count + 1) // 2)
                sess = _make_session(student, "in_progress", answered)
                for idx, snapshot in enumerate(snapshots[:answered]):
                    _answer(sess, idx, snapshot, accuracy=0.4)

        # none_student：不开会话（未开始）
        _ = none_student
        session.flush()

    return assignments


def _typo(headword: str) -> str:
    if len(headword) > 4:
        return headword[:-1]
    return headword + "x"


def seed_review_states(
    session: Session,
    tenant: Tenant,
    students: list[Student],
    level_books: dict[str, VocabularyBook],
) -> int:
    """8 名学生 × 3 词造 FSRS 状态，due_at 覆盖过去 / 本周 / 未来。

    选词跨 KET / CET4 / IELTS_TOEFL 三个任务词库，保证近期周期快照词条与
    复习状态有交集，趋势报告的 ``due_unreviewed`` 可回算出非零值。
    """
    pool: list[VocabularyWord] = []
    for level in ("KET", "CET4", "IELTS_TOEFL"):
        pool.extend(_book_words(session, level_books[level])[:8])
    now = datetime.now(UTC)
    states = 0

    for index, word in enumerate(pool):
        student = students[index % 8]
        k = index % 3
        capability = "spelling" if k % 2 == 0 else "recognition"
        bucket = index % 3
        if bucket == 0:  # 过去：到期未复习
            due_at = now - timedelta(days=1 + (index % 4))
            state, reps, lapses = "learning", 1, 1
            last_review = now - timedelta(days=3)
            last_rating, last_correct = "again", False
            interval_days = 1
        elif bucket == 1:  # 本周到期
            due_at = now + timedelta(days=index % 3)
            state, reps, lapses = "learning", 2, 0
            last_review = now - timedelta(days=1)
            last_rating, last_correct = "good", True
            interval_days = 2
        else:  # 未来到期
            due_at = now + timedelta(days=3 + (index % 8))
            state, reps, lapses = "review", 4, 0
            last_review = now - timedelta(days=7)
            last_rating, last_correct = "good", True
            interval_days = 7

        session.add(
            VocabularyReviewState(
                tenant_id=tenant.id,
                user_id=student.user_id,  # type: ignore[arg-type]
                word_id=word.id,
                capability=capability,
                state=state,
                stability=float(reps),
                difficulty=5.0,
                reps=reps,
                lapses=lapses,
                interval_days=interval_days,
                due_at=due_at,
                last_review_at=last_review,
                last_rating=last_rating,
                last_is_correct=last_correct,
            )
        )
        states += 1
    session.flush()
    return states


def seed_pk(
    session: Session,
    tenant: Tenant,
    teacher: User,
    room: Classroom,
    students: list[Student],
    level_books: dict[str, VocabularyBook],
    anchor: date,
) -> dict[str, int]:
    """2 场已结束 1v1 PK：大厅 + 对局 + 玩家 + 作答，不影响任务统计。"""
    pairs = [
        (level_books["KET"], students[0], students[1], -12),
        (level_books["PET"], students[2], students[3], -6),
    ]
    lobby_count = match_count = player_count = answer_count = 0

    for book, winner, loser, week_offset in pairs:
        words = _book_words(session, book)[:6]
        snapshots = _build_snapshots(words, ["meaning"])
        started_at = _anchor_dt(anchor, days=week_offset, hour=10)
        finished_at = started_at + timedelta(minutes=10)

        lobby = VocabPkLobby(
            tenant_id=tenant.id,
            classroom_id=room.id,
            created_by=teacher.id,
            book_id=book.id,
            prompt_types=["meaning"],
            question_count=6,
            per_question_seconds=20,
            status="closed",
            snapshot_items=snapshots,
            closed_at=finished_at,
        )
        session.add(lobby)
        session.flush()
        lobby_count += 1

        match = VocabPkMatch(
            tenant_id=tenant.id,
            lobby_id=lobby.id,
            classroom_id=room.id,
            snapshot_items=snapshots,
            question_count=6,
            per_question_seconds=20,
            status="finished",
            current_item_index=6,
            started_at=started_at,
            finished_at=finished_at,
            end_reason="manual",
            winner_student_id=winner.id,
            state_version=2,
        )
        session.add(match)
        session.flush()
        match_count += 1

        players = [
            (winner, "left", 5, 5, 42.0),
            (loser, "right", 3, 3, 58.0),
        ]
        player_rows: list[VocabPkPlayer] = []
        for student, side, score, correct, total_seconds in players:
            player = VocabPkPlayer(
                tenant_id=tenant.id,
                lobby_id=lobby.id,
                match_id=match.id,
                classroom_id=room.id,
                student_id=student.id,
                side=side,
                status="finished",
                score=score * 100,
                answered_count=6,
                correct_count=correct,
                total_seconds=total_seconds,
                joined_at=started_at,
                finished_at=finished_at,
            )
            session.add(player)
            session.flush()
            player_rows.append(player)
            player_count += 1

        for player, (student, _side, _score, correct, _sec) in zip(
            player_rows, players, strict=True
        ):
            for idx, snapshot in enumerate(snapshots):
                is_correct = idx < correct
                headword = str(snapshot["headword"])
                raw = headword if is_correct else _typo(headword)
                base_score = 100 if is_correct else 0
                speed_bonus = rng_speed_bonus(idx, is_correct)
                session.add(
                    VocabPkAnswer(
                        tenant_id=tenant.id,
                        match_id=match.id,
                        player_id=player.id,
                        student_id=student.id,
                        item_index=idx,
                        prompt_type="meaning",
                        answer_raw=raw,
                        answer_normalized=vocab_service.normalize_spelling(raw),
                        is_correct=is_correct,
                        base_score=base_score,
                        speed_bonus=speed_bonus,
                        score=base_score + speed_bonus,
                        latency_ms=300 + idx * 120,
                        answered_at=started_at + timedelta(seconds=idx * 12),
                        idempotency_key=f"demo-pk-{uuid.uuid4().hex}",
                    )
                )
                answer_count += 1
    session.flush()
    return {
        "lobbies": lobby_count,
        "matches": match_count,
        "players": player_count,
        "answers": answer_count,
    }


def rng_speed_bonus(idx: int, is_correct: bool) -> int:
    if not is_correct:
        return 0
    return max(0, 40 - idx * 5)


def seed_farm(
    session: Session,
    tenant: Tenant,
    students: list[Student],
    anchor: date,
) -> dict[str, int]:
    """5 个农场地块 + 4 枚农场徽章。"""
    plots = 0
    badges = 0
    specs = [
        (students[0], 22, 3, True),
        (students[1], 14, 1, True),
        (students[2], 7, 0, False),
        (students[3], 2, 0, False),
        (students[4], 20, 2, True),
    ]
    harvested_at = _anchor_dt(anchor, days=-2, hour=18)
    for student, growth, harvest_count, harvested in specs:
        session.add(
            VocabFarmPlot(
                tenant_id=tenant.id,
                user_id=student.user_id,  # type: ignore[arg-type]
                growth_points=growth,
                today_points=min(growth, 5),
                last_points_date=anchor,
                today_farm_xp=min(growth, 5),
                last_farm_xp_date=anchor,
                harvest_count=harvest_count,
                last_harvested_at=harvested_at if harvested else None,
            )
        )
        plots += 1

    badge_rows = [
        (students[0], "farm_harvest_7"),
        (students[0], "farm_first_harvest"),
        (students[1], "farm_first_harvest"),
        (students[4], "farm_first_harvest"),
    ]
    for student, key in badge_rows:
        session.add(
            StudentBadge(
                tenant_id=tenant.id,
                student_id=student.id,
                badge_key=key,
                awarded_at=harvested_at,
            )
        )
        badges += 1
    session.flush()
    return {"plots": plots, "badges": badges}


def main() -> None:
    engine = safe_engine()
    anchor = _anchor_date()
    grouped = _load_words()

    # 兼容 C 后端：assignment.source_book_ids 列可能尚未落地
    inspector = inspect(engine)
    assignment_cols = {
        c["name"] for c in inspector.get_columns("vocabulary_assignment")
    }
    has_source_book_ids = "source_book_ids" in assignment_cols

    password = os.environ.get(PASSWORD_ENV) or DEFAULT_DEMO_PASSWORD
    pw_hash = get_password_hash(password)

    # 先在跨租户通道解析/创建演示租户根行（tenant 表不在 RLS 隔离清单）。
    with Session(engine) as resolve_session:
        tenant = ensure_tenant(resolve_session)
        resolve_session.commit()
        tenant_id = tenant.id

    # 全部写入包在 vocabdemo 租户上下文内；每个模型构造时显式带 tenant_id，
    # 不依赖 ORM 默认租户兜底（避免漏写时落到默认租户）。
    with tenant_scope(tenant_id), Session(engine) as session:
        # 幂等：先清空旧 demo 命名空间（护栏见 cleanup_demo.py）；
        # 保留租户根行与模块授权行，子表重建后挂回同一租户。
        reset_demo_namespace(session, keep_tenant=True)
        tenant = session.get(Tenant, tenant_id)

        ensure_module(session, tenant)
        teacher = ensure_teacher(session, tenant, pw_hash)
        ensure_admin(session, tenant, pw_hash)
        rooms = ensure_classrooms(session, tenant, teacher)
        students_by_room = ensure_students(session, tenant, rooms, pw_hash)
        demo1_students = students_by_room[CLASSROOM_DEMO1]
        demo2_students = students_by_room[CLASSROOM_DEMO2]

        level_books = seed_level_books(session, tenant, teacher, grouped)
        license_books = seed_license_books(session, tenant, teacher, grouped, anchor)
        assignments = seed_assignments(
            session,
            tenant,
            teacher,
            rooms[CLASSROOM_DEMO1],
            demo1_students,
            level_books,
            anchor,
            has_source_book_ids=has_source_book_ids,
        )
        review_states = seed_review_states(session, tenant, demo1_students, level_books)
        pk_stats = seed_pk(
            session,
            tenant,
            teacher,
            rooms[CLASSROOM_DEMO1],
            demo1_students,
            level_books,
            anchor,
        )
        farm_stats = seed_farm(session, tenant, demo1_students, anchor)

        session.commit()

        # ── 汇总输出 ──────────────────────────────────────────────────
        word_total = sum(len(_book_words(session, b)) for b in level_books.values())
        license_word_total = sum(
            len(_book_words(session, b)) for b in license_books.values()
        )
        version_rows = session.exec(
            select(VocabularyBookVersion).where(
                VocabularyBookVersion.tenant_id == tenant.id
            )
        ).all()
        audit_rows = session.exec(
            select(VocabularyLicenseAudit).where(
                VocabularyLicenseAudit.tenant_id == tenant.id
            )
        ).all()

        print("本地演示数据种子完成（demo-only，不进生产）：")
        print(f"  五级演示词库: {len(level_books)} 个，词条 {word_total} 个")
        print(f"  授权演示词库: {len(license_books)} 个，词条 {license_word_total} 个")
        print(
            f"  词库版本快照: {len(version_rows)} 行（KET 3 版 / 教材 2 版 / 其余各 1 版）"
        )
        print(f"  授权审计行: {len(audit_rows)} 条")
        print(
            f"  课堂: {CLASSROOM_DEMO1}（{len(demo1_students)} 学生）、"
            f"{CLASSROOM_DEMO2}（{len(demo2_students)} 学生）"
        )
        print(f"  教师账号: {TEACHER_EMAIL}（口令由环境变量 {PASSWORD_ENV} 提供）")
        print(
            f"  管理员账号: {ADMIN_EMAIL}（role=school_admin，"
            f"口令由环境变量 {PASSWORD_ENV} 提供）"
        )
        print(
            f"  学生账号: {STUDENT_EMAIL_PREFIX}01..{len(demo1_students):02d}@example.com 等"
        )
        print(f"  教师任务: {len(assignments)} 个")
        print(f"  FSRS 复习状态: {review_states} 行")
        print(
            f"  PK: {pk_stats['lobbies']} 大厅 / {pk_stats['matches']} 对局 / "
            f"{pk_stats['players']} 玩家 / {pk_stats['answers']} 作答"
        )
        print(f"  农场: {farm_stats['plots']} 地块 / {farm_stats['badges']} 徽章")
        if not has_source_book_ids:
            print("  注意: 本地库尚无 source_book_ids 列，种子已按缺列兼容路径写入。")


if __name__ == "__main__":
    main()
