#!/usr/bin/env python3
"""本地试点数据集种子：两所学校 + 班级 + 师生 + 真实体量作答。

为什么需要它（2026-11-17）：本地开发库长期只有 15 用户 / 1 学生 / 0 作答，
导致 ① 恢复演练只能验机制不能验业务（没有录音与成绩可回放重算）；
② 性能基线没有体量；③ 前端大多在空列表上跑。本脚本造一套贴近试点的
最小真实数据，让这些验收有东西可跑。

纪律：
- 只动**租户前缀 `seedpilot` 的学校**与其下数据，不碰默认校（默认校是演示校）；
- 幂等：按 slug 判断已存在则跳过，`--reset` 只清理自己造的数据；
- 用 admin 连接写库（种子与 `initial_data.py` 同口径：固定租户由脚本指定，绕 RLS）；
- 音频写真实文件（0.5s 静音 wav），保证「备份/恢复演练能否还原音频卷」可验。

用法（容器内跑，路径与 AUDIO_STORAGE_DIR 一致）：
    docker compose exec backend python scripts/seed_pilot_dataset.py
    docker compose exec backend python scripts/seed_pilot_dataset.py --reset
    docker compose exec backend python scripts/seed_pilot_dataset.py --classes 4 --students 25
"""

from __future__ import annotations

import argparse
import io
import random
import uuid
import wave
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.security import get_password_hash
from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    Passage,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Student,
    Tenant,
    User,
)

SEED_PREFIX = "seedpilot"
SEED_TITLE_PREFIX = "[seed] "
DEFAULT_PASSWORD = "SeedPilot2026"

PASSAGE_TEXTS = [
    (
        "The Morning Market",
        "Every Saturday the market opens before sunrise. Farmers bring vegetables, and the smell of fresh bread fills the street. I always buy two apples and a small loaf.",
    ),
    (
        "Learning to Swim",
        "My daughter learned to swim last summer. At first she was afraid of the deep water. After ten lessons she could cross the pool without stopping.",
    ),
    (
        "A Letter from Home",
        "When I lived abroad, my mother wrote me a letter every month. The letters were short, but they reminded me that someone was thinking of me.",
    ),
    (
        "The Night Train",
        "The night train leaves at ten and arrives at six. I like watching the small stations pass by in the dark. It feels like travelling through another world.",
    ),
    (
        "Repairing the Bicycle",
        "My bicycle broke on the way to work. A kind man in a small shop fixed the chain in fifteen minutes and refused to take my money.",
    ),
    (
        "City in the Rain",
        "Rain changes the city. People walk faster, umbrellas appear, and the streets shine like mirrors. I usually stay home and read on such days.",
    ),
    (
        "First Day at Work",
        "On my first day, I forgot everyone's name within an hour. My manager said it was normal and gave me a list to study at home.",
    ),
    (
        "Cooking Together",
        "We cook dinner together every Friday. My son cuts the vegetables and I prepare the soup. The kitchen becomes loud and warm.",
    ),
    (
        "The Old Library",
        "The library near my house was built in 1920. The wooden floors creak, but the reading room is quiet and full of light.",
    ),
    (
        "A Small Garden",
        "I grow tomatoes on my balcony. It is only two metres wide, but in August I have more tomatoes than I can eat.",
    ),
    (
        "Waiting for the Bus",
        "The bus is often late in winter. People stand close together and talk about the weather until it finally arrives.",
    ),
    (
        "A New Language",
        "Learning a new language is slow work. You forget words, then remember them months later. Progress is invisible until one day you understand a whole conversation.",
    ),
]

TRANSCRIPTS = [
    "Every saturday the market opens before sunrise and farmers bring vegetables",
    "my daughter learned to swim last summer and at first she was afraid of the deep water",
    "The night train leaves at ten and arrives at six I like watching the small stations",
    "Rain changes the city people walk faster and umbrellas appear",
    "I grow tomatoes on my balcony it is only two metres wide",
]

SCENARIO_QUESTIONS = [
    "What do you usually do on weekends?",
    "Describe a place in your city that you like.",
    "How do you prepare for an exam?",
    "Why do people enjoy travelling?",
]


@dataclass
class SeedContent:
    passages: list[Passage]
    repeats: list[RepeatSentence]
    questions: list[ScenarioQuestion]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Seed a pilot-sized local dataset")
    ap.add_argument(
        "--schools", type=int, default=2, help="造几所学校（含新增的第二校）"
    )
    ap.add_argument("--classes", type=int, default=3, help="每校班级数")
    ap.add_argument("--students", type=int, default=20, help="每班学生数")
    ap.add_argument("--attempts", type=int, default=4, help="每名学生作答题数")
    ap.add_argument("--password", default=DEFAULT_PASSWORD, help="种子账号初始密码")
    ap.add_argument("--reset", action="store_true", help="先清掉上次造的数据再重建")
    return ap.parse_args()


def silent_wav_bytes(seconds: float = 0.5, rate: int = 8000) -> bytes:
    """生成一段静音 wav，用作占位录音（体积小，但确实是可解码的音频文件）。"""

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def reset_seed(session: Session) -> None:
    """只删自己造的数据：租户 → 其下 user/classroom/student/attempt + 本校内容。"""
    tenants = session.exec(
        select(Tenant).where(Tenant.slug.like(f"{SEED_PREFIX}%"))
    ).all()
    if not tenants:
        print("没有可清理的 seed 租户")
        return
    for t in tenants:
        for stmt in (
            "delete from attempt where tenant_id = :t",
            "delete from practice_session where tenant_id = :t",
            "delete from classroom_exercise where tenant_id = :t",
            "delete from student where tenant_id = :t",
            "delete from classroom where tenant_id = :t",
            "delete from scenario_question where tenant_id = :t",
            "delete from scenario where tenant_id = :t",
            "delete from repeat_sentence where tenant_id = :t",
            "delete from passage where tenant_id = :t",
            'delete from "user" where tenant_id = :t',
        ):
            session.execute(text(stmt), {"t": str(t.id)})
        session.execute(text("delete from tenant where id = :t"), {"t": str(t.id)})
        print(f"已清理租户 {t.slug}")
    # 兜底：修好租户归属之前，篇目曾建在默认校
    session.execute(
        text("delete from passage where title like :p"), {"p": f"{SEED_TITLE_PREFIX}%"}
    )
    session.commit()


def ensure_content(
    session: Session, tenant: Tenant, owner_id: uuid.UUID | None, count: int
) -> SeedContent:
    """按校建内容：篇目 + 每篇一句复述 + 一个情景主题下的问法。

    内容必须归属本校：`content_access.require_same_tenant` 与 RLS 都会拦
    跨校取题（把篇目建在默认校时，种子校学生提交作答直接 404）。
    """
    passages = session.exec(
        select(Passage).where(
            Passage.tenant_id == tenant.id,
            Passage.title.like(f"{SEED_TITLE_PREFIX}%"),
        )
    ).all()
    for i in range(count):
        title, body = PASSAGE_TEXTS[i % len(PASSAGE_TEXTS)]
        name = f"{SEED_TITLE_PREFIX}{title} {i + 1}"
        if any(p.title == name for p in passages):
            continue
        base_slug = "-".join(
            "".join(ch if ch.isalnum() else " " for ch in name).lower().split()
        )[:90]
        p = Passage(
            title=name,
            slug=crud.unique_passage_slug(session, base_slug, tenant_id=tenant.id),
            topic="pilot",
            cefr_band="B1",
            text=body,
            suggested_seconds=45,
            tenant_id=tenant.id,
            owner_id=owner_id,
        )
        session.add(p)
        passages.append(p)
    session.commit()

    repeats = session.exec(
        select(RepeatSentence).where(RepeatSentence.tenant_id == tenant.id)
    ).all()
    for p in passages:
        if any(r.passage_id == p.id for r in repeats):
            continue
        first = p.text.split(". ")[0].rstrip(".") + "."
        r = RepeatSentence(
            tenant_id=tenant.id,
            passage_id=p.id,
            order_index=0,
            text=first,
            suggested_seconds=10,
            owner_id=owner_id,
        )
        session.add(r)
        repeats.append(r)

    topic = f"{SEED_PREFIX}-topic-{tenant.slug}"
    scenario = session.exec(
        select(Scenario).where(Scenario.tenant_id == tenant.id, Scenario.topic == topic)
    ).first()
    if scenario is None:
        scenario = Scenario(topic=topic, tenant_id=tenant.id, owner_id=owner_id)
        session.add(scenario)
    session.commit()
    session.refresh(scenario)

    questions = session.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.scenario_id == scenario.id)
    ).all()
    if not questions:
        for i, text in enumerate(SCENARIO_QUESTIONS):
            q = ScenarioQuestion(
                tenant_id=tenant.id,
                scenario_id=scenario.id,
                order_index=i,
                text=text,
                suggested_seconds=20,
                owner_id=owner_id,
            )
            session.add(q)
            questions.append(q)
    session.commit()
    for group in (passages, repeats, questions):
        for x in group:
            session.refresh(x)
    print(
        f"学校 {tenant.slug} 内容：{len(passages)} 篇目 / {len(repeats)} 复述句 / {len(questions)} 问法"
    )
    return SeedContent(passages=passages, repeats=repeats, questions=questions)


def ensure_tenant(
    session: Session, idx: int, classes: int, n_students: int, password_hash: str
) -> tuple[Tenant, list[Classroom], list[Student], list[User]]:
    slug = f"{SEED_PREFIX}-{idx:02d}"
    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if tenant:
        print(f"学校 {slug} 已存在，跳过造校")
        cls = session.exec(
            select(Classroom).where(Classroom.tenant_id == tenant.id)
        ).all()
        stu = session.exec(select(Student).where(Student.tenant_id == tenant.id)).all()
        usr = session.exec(select(User).where(User.tenant_id == tenant.id)).all()
        return tenant, cls, stu, usr

    tenant = Tenant(
        slug=slug,
        name_zh=f"试点测试学校{idx}（seed）",
        name_en=f"Pilot Seed School {idx}",
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    # 校级管理员（用于验证管理面板/开校停用等页面）
    admin = User(
        email=f"admin@{slug}.seed",
        full_name=f"学校管理员{idx}",
        role="school_admin",
        tenant_id=tenant.id,
        hashed_password=password_hash,
    )
    session.add(admin)
    session.commit()

    classrooms, students, teachers = [], [], []
    for c in range(classes):
        code = f"SD{idx}{c:02d}X"[:16]
        teacher = User(
            email=f"t{c + 1:02d}@{slug}.seed",
            full_name=f"教师{idx}-{c + 1}",
            role="teacher",
            tenant_id=tenant.id,
            hashed_password=password_hash,
        )
        session.add(teacher)
        session.flush()
        room = Classroom(
            code=code,
            name=f"试点班 {idx}-{c + 1}",
            grade="Grade 8",
            teaching_goal="seed 数据集：跟读与情景问答",
            class_size=n_students,
            owner_id=teacher.id,
            tenant_id=tenant.id,
        )
        session.add(room)
        session.flush()
        teachers.append(teacher)
        classrooms.append(room)

        for s in range(n_students):
            uname = f"s{idx}{c:02d}{s + 1:02d}"
            stu_user = User(
                username=uname,
                email=None,
                full_name=f"学生{idx}-{c + 1}-{s + 1}",
                role="student",
                tenant_id=tenant.id,
                hashed_password=password_hash,
            )
            session.add(stu_user)
            session.flush()
            stu = Student(
                classroom_id=room.id,
                user_id=stu_user.id,
                display_name=f"学生{c + 1}-{s + 1}",
                tenant_id=tenant.id,
                xp=random.randint(0, 900),
                streak_days=random.randint(0, 9),
                last_practice_date=(
                    datetime.now(UTC) - timedelta(days=random.randint(0, 6))
                ).date(),
            )
            session.add(stu)
            students.append(stu)
    session.commit()
    for o in (classrooms, students, teachers):
        for x in o:
            session.refresh(x)
    print(
        f"学校 {slug}：{len(classrooms)} 班 / {len(teachers)} 教师 / {len(students)} 学生"
    )
    return tenant, classrooms, students, teachers + [admin]


def ensure_exercise(
    session: Session, tenant: Tenant, room: Classroom, content: SeedContent
) -> ClassroomExercise:
    """每班一次「已发布练习」：教师面板的骨架与统计都以它为准。

    没有发布会话时，即使库里有作答，教师端也只显示「已提交 0/20」——
    作答必须挂在 session 上、session 必须挂当前发布快照，才会被面板统计。
    """
    if room.current_exercise_id:
        existing = session.get(ClassroomExercise, room.current_exercise_id)
        if existing is not None:
            return existing

    passage = content.passages[0]
    repeat = next(
        (r for r in content.repeats if r.passage_id == passage.id), content.repeats[0]
    )
    questions = content.questions[:2]
    items: list[dict[str, object]] = [
        {
            "type": "passage",
            "id": str(passage.id),
            "text": passage.text,
            "translation": passage.translation,
            "audio_url": passage.audio_url,
            "suggested_seconds": passage.suggested_seconds,
            "replay_limit": 0,
            "band": passage.cefr_band,
        },
        {
            "type": "repeat",
            "id": str(repeat.id),
            "text": repeat.text,
            "translation": repeat.translation,
            "audio_url": repeat.audio_url,
            "suggested_seconds": repeat.suggested_seconds,
            "replay_limit": repeat.replay_limit,
            "band": passage.cefr_band,
        },
    ]
    for q in questions:
        items.append(
            {
                "type": "question",
                "id": str(q.id),
                "text": q.text,
                "translation": q.translation,
                "audio_url": q.audio_url,
                "suggested_seconds": q.suggested_seconds,
                "replay_limit": 0,
                "band": q.band,
            }
        )

    exercise = ClassroomExercise(
        tenant_id=tenant.id,
        classroom_id=room.id,
        version_no=1,
        title="seed 今日练习",
        status="published",
        snapshot_items=items,
        created_by=room.owner_id,
    )
    session.add(exercise)
    session.flush()
    room.current_exercise_id = exercise.id
    session.add(room)
    session.commit()
    session.refresh(exercise)
    return exercise


def ensure_sessions(
    session: Session,
    tenant: Tenant,
    students: list[Student],
    rooms: dict[uuid.UUID, Classroom],
    exercises: dict[uuid.UUID, ClassroomExercise],
    passage_id: uuid.UUID | None,
) -> dict[uuid.UUID, PracticeSession]:
    """每名学生一条「今日 daily 会话」，绑定本班当前发布快照。

    面板只读 `session_date == 今天` 的 daily 会话，所以种子作答必须落在今天。
    """
    today = datetime.now(ZoneInfo(settings.PRACTICE_TZ)).date()
    existing = session.exec(
        select(PracticeSession).where(
            PracticeSession.tenant_id == tenant.id,
            PracticeSession.session_date == today,
            PracticeSession.mode == "daily",
        )
    ).all()
    by_student = {ps.student_id: ps for ps in existing}
    for stu in students:
        if stu.id in by_student:
            continue
        room = rooms[stu.classroom_id]
        ps = PracticeSession(
            tenant_id=tenant.id,
            classroom_id=room.id,
            student_id=stu.id,
            band="B1",
            question_band="B1",
            stars=3,
            mode="daily",
            passage_id=passage_id,
            assignment_id=exercises[room.id].id,
            session_date=today,
        )
        session.add(ps)
        by_student[stu.id] = ps
    session.commit()
    for ps in by_student.values():
        session.refresh(ps)
    return by_student


def ensure_attempts(
    session: Session,
    tenant: Tenant,
    students: list[Student],
    exercises: dict[uuid.UUID, ClassroomExercise],
    sessions: dict[uuid.UUID, PracticeSession],
    per_student: int,
    audio_dir: Path,
) -> int:
    audio_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    day_start = datetime.now(ZoneInfo(settings.PRACTICE_TZ)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    for stu in students:
        exercise = exercises[stu.classroom_id]
        items = [i for i in exercise.snapshot_items if i.get("type") != "instruction"]
        for k, item in enumerate(items[:per_student]):
            item_type = str(item["type"])
            item_id = uuid.UUID(str(item["id"]))
            # 作答时间落在“今天”之内：面板按今日会话统计，跨日会让提交数变 0
            created = day_start + timedelta(
                hours=random.randint(7, 21), minutes=random.randint(0, 59)
            )
            name = f"{uuid.uuid4().hex}.wav"
            audio_file = audio_dir / name
            audio_file.write_bytes(silent_wav_bytes())
            base = random.randint(68, 95)
            att = Attempt(
                tenant_id=tenant.id,
                item_type=item_type,
                item_id=item_id,
                student_id=stu.id,
                session_id=sessions[stu.id].id,
                idempotency_key=f"seed-{uuid.uuid4().hex}",
                item_snapshot={"seed": True, "index": k + 1, "type": item_type},
                audio_path=str(audio_file),
                audio_mime="audio/wav",
                duration_s=round(random.uniform(8.0, 42.0), 1),
                status="done",
                engine="mock",
                transcript=random.choice(TRANSCRIPTS),
                completeness=max(0, min(100, base + random.randint(-8, 5))),
                fluency=max(0, min(100, base + random.randint(-6, 8))),
                accuracy=max(0, min(100, base + random.randint(-10, 6))),
                overall=max(0, min(100, base + random.randint(-5, 5))),
                advice=["注意句尾降调", "长句可适当停顿"],
                created_at=created,
            )
            session.add(att)
            # 逐条提交：一条脏数据不该拖垮整锅，也便于分批写不撑爆内存
            session.commit()
            made += 1
    return made


def main() -> None:
    args = parse_args()
    engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    audio_dir = Path(settings.AUDIO_STORAGE_DIR)
    with Session(engine) as session:
        if args.reset:
            reset_seed(session)
        pw_hash = get_password_hash(args.password)

        total = {
            "schools": 0,
            "classes": 0,
            "students": 0,
            "attempts": 0,
            "sessions": 0,
        }
        for i in range(1, args.schools + 1):
            tenant, cls, stu, users = ensure_tenant(
                session, i, args.classes, args.students, pw_hash
            )
            total["schools"] += 1
            total["classes"] += len(cls)
            total["students"] += len(stu)
            teachers = [u for u in users if u.role == "teacher"]
            content = ensure_content(
                session, tenant, teachers[0].id if teachers else None, 12
            )
            rooms = {room.id: room for room in cls}
            exercises = {
                rid: ensure_exercise(session, tenant, room, content)
                for rid, room in rooms.items()
            }
            sessions = ensure_sessions(
                session,
                tenant,
                stu,
                rooms,
                exercises,
                content.passages[0].id if content.passages else None,
            )
            total["sessions"] += len(sessions)
            if (
                args.attempts
                and not session.exec(
                    select(Attempt).where(Attempt.tenant_id == tenant.id).limit(1)
                ).first()
            ):
                n = ensure_attempts(
                    session,
                    tenant,
                    stu,
                    exercises,
                    sessions,
                    args.attempts,
                    audio_dir,
                )
                total["attempts"] += n
            else:
                print(f"学校 {tenant.slug} 已有作答，跳过造作答")

    print("\n=== 种子完成 ===")
    print(
        f"学校 {total['schools']} / 班级 {total['classes']} / 学生 {total['students']} / "
        f"会话 {total['sessions']} / 作答 {total['attempts']}"
    )
    print(
        f"账号：学校管理员 admin@seedpilot-01.seed、教师 t01@seedpilot-01.seed、学生 s10001..（登录带 school=seedpilot-01），统一密码 {args.password}"
    )
    engine.dispose()


if __name__ == "__main__":
    main()
