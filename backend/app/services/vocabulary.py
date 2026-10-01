"""词汇学习域逻辑：判分规范化、发布快照、会话/作答状态机、统计聚合。

路由层（api/routes/vocabulary.py）只做参数与权限，业务不变量在这里：
- 判分确定性：Unicode NFKC + 去首尾空白 + casefold，只接受快照里的
  标准拼写与显式配置的变体，不调用大模型。
- 快照不可变：发布时深拷贝词条内容；词库后续编辑不改变进行中任务
  与历史报告。
- 统计口径：教师统计与错词本默认看首答（attempt_no=1），练习重试
  不冲高正确率；零作答显示 not_started 而非 0%。
"""

import unicodedata
import uuid
from collections import Counter
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    VOCAB_PROMPT_TYPES,
    Student,
    User,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularyBook,
    VocabularyBookItem,
    VocabularySession,
    VocabularyWord,
    get_datetime_utc,
)

MAX_TASK_WORDS = 100


def normalize_spelling(raw: str) -> str:
    """判分前规范化：NFKC（全角→半角等）+ 首尾空白 + casefold。

    不折叠内部空白、不去连字符/撇号——变体只认快照显式配置。
    """
    return unicodedata.normalize("NFKC", raw).strip().casefold()


def accepted_forms(snapshot_item: dict[str, object]) -> set[str]:
    """快照条目的全部可接受拼写（规范化后）。"""
    forms = {normalize_spelling(str(snapshot_item["headword"]))}
    extras = snapshot_item.get("accepted_spellings")
    if isinstance(extras, list):
        forms.update(normalize_spelling(str(extra)) for extra in extras if str(extra))
    forms.discard("")
    return forms


def check_spelling(answer: str, snapshot_item: dict[str, object]) -> bool:
    return normalize_spelling(answer) in accepted_forms(snapshot_item)


def build_word_snapshot(
    word: VocabularyWord, prompt_types: list[str]
) -> dict[str, object]:
    """把词条当前内容深拷贝进发布快照（与练习模块同口径）。"""
    return {
        "word_id": str(word.id),
        "headword": word.headword,
        "part_of_speech": word.part_of_speech,
        "meaning_zh": word.meaning_zh,
        "meaning_en": word.meaning_en,
        "accepted_spellings": list(word.accepted_spellings or []),
        "example_en": word.example_en,
        "audio_url": word.audio_url,
        "prompt_types": list(prompt_types),
    }


def validate_prompt_types(prompt_types: list[str]) -> list[str]:
    cleaned: list[str] = []
    for prompt_type in prompt_types:
        if prompt_type not in VOCAB_PROMPT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"未知出题方式：{prompt_type}（可选：看义/听音）",
            )
        if prompt_type not in cleaned:
            cleaned.append(prompt_type)
    if not cleaned:
        raise HTTPException(status_code=422, detail="至少选择一种出题方式")
    return cleaned


def visible_book_ids_for(session: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """教师可用的词库 id 集合：全部公共词库 + 自己名下的班级词库（管理员另走全通过）。"""
    rows = session.exec(
        select(VocabularyBook.id).where(
            (VocabularyBook.scope == "public") | (VocabularyBook.owner_id == user_id)  # type: ignore[operator]
        )
    ).all()
    return set(rows)


def resolve_publish_words(
    session: Session,
    book_id: uuid.UUID | None,
    word_ids: list[uuid.UUID] | None,
    viewer: User,
) -> list[VocabularyWord]:
    """发布词单解析：整本词库（active 词、按 position）或显式词清单。

    权限：来源词库必须对发布教师可见（公共库或本人班级库；管理员不限），
    显式 word_ids 的每个词也必须归属至少一本可见词库——否则可借发布/结果
    接口读到其他教师私有词条的拼写与释义。

    发布校验三口径：所选词数、可出题数、最终题数一致（题量不允许
    超过实际可出题量——清单里多余/归档词直接 422，避免静默缩水）。
    """
    allowed_book_ids: set[uuid.UUID] | None = (
        None if viewer.is_superuser else visible_book_ids_for(session, viewer.id)
    )

    def _book_allowed(book: VocabularyBook) -> bool:
        return allowed_book_ids is None or book.id in allowed_book_ids

    words: list[VocabularyWord]
    if book_id is not None:
        book = session.get(VocabularyBook, book_id)
        if book is None or book.status != "active":
            raise HTTPException(status_code=404, detail="词库不存在或已归档")
        if not _book_allowed(book):
            raise HTTPException(status_code=403, detail="没有权限使用这个词库")
        words = list(
            session.exec(
                select(VocabularyWord)
                .join(
                    VocabularyBookItem,
                    VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
                )
                .where(
                    VocabularyBookItem.book_id == book_id,  # type: ignore[arg-type]
                    VocabularyWord.status == "active",
                )
                .order_by(col(VocabularyBookItem.position))
            ).all()
        )
        if not words:
            raise HTTPException(status_code=422, detail="词库里没有可用词条")
        return words

    if not word_ids:
        raise HTTPException(status_code=422, detail="需要指定词库或词清单")
    if len(word_ids) > MAX_TASK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"一次发布最多 {MAX_TASK_WORDS} 个词"
        )
    if len(set(word_ids)) != len(word_ids):
        raise HTTPException(status_code=422, detail="词清单内有重复词条")
    found = {
        w.id: w
        for w in session.exec(
            select(VocabularyWord).where(col(VocabularyWord.id).in_(word_ids))  # type: ignore[operator]
        ).all()
    }
    missing_or_inactive = [
        str(wid)
        for wid in word_ids
        if found.get(wid) is None or found[wid].status != "active"
    ]
    if missing_or_inactive:
        raise HTTPException(
            status_code=422,
            detail=f"词清单包含不存在或已归档的词条（{len(missing_or_inactive)} 个），请重新选择",
        )
    if allowed_book_ids is not None:
        # 显式清单同样要核验归属：每个词必须出现在至少一本可见词库里
        owning_book_rows = session.exec(
            select(VocabularyBookItem.word_id, VocabularyBookItem.book_id).where(
                col(VocabularyBookItem.word_id).in_(word_ids)  # type: ignore[operator]
            )
        ).all()
        visible_word_ids = {
            word_id
            for word_id, book_id_of_item in owning_book_rows
            if book_id_of_item in allowed_book_ids
        }
        not_allowed = [str(wid) for wid in word_ids if wid not in visible_word_ids]
        if not_allowed:
            raise HTTPException(
                status_code=403,
                detail=f"词清单包含你没有权限使用的词条（{len(not_allowed)} 个），请从自己的词库重新选择",
            )
    # 保持请求顺序（教师预览里看到的顺序即学生作答顺序）
    return [found[wid] for wid in word_ids]


def next_assignment_version(session: Session, classroom_id: uuid.UUID) -> int:
    latest = session.exec(
        select(VocabularyAssignment.version_no)
        .where(VocabularyAssignment.classroom_id == classroom_id)
        .order_by(col(VocabularyAssignment.version_no).desc())
    ).first()
    return (latest or 0) + 1


def current_published_assignment(
    session: Session, classroom_id: uuid.UUID
) -> VocabularyAssignment | None:
    return session.exec(
        select(VocabularyAssignment)
        .where(
            VocabularyAssignment.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularyAssignment.status == "published",
        )
        .order_by(col(VocabularyAssignment.version_no).desc())
    ).first()


def publish_assignment(
    session: Session,
    classroom_id: uuid.UUID,
    created_by: uuid.UUID | None,
    title: str | None,
    words: list[VocabularyWord],
    prompt_types: list[str],
    mode: str = "practice",
    due_at: datetime | None = None,
) -> VocabularyAssignment:
    """发布：快照写入、目标名单固化、旧任务归档，同一事务内完成。"""
    if not words:
        raise HTTPException(status_code=422, detail="词汇任务至少需要一个词")
    if len(words) > MAX_TASK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"一次发布最多 {MAX_TASK_WORDS} 个词"
        )
    if mode not in {"practice", "quiz"}:
        raise HTTPException(status_code=422, detail="未知任务模式")
    if mode == "quiz":
        raise HTTPException(
            status_code=422, detail="测验模式将在下一阶段开放，请先使用练习模式"
        )
    if due_at is not None and due_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="截止时间必须晚于现在")
    students = session.exec(
        select(Student).where(Student.classroom_id == classroom_id)  # type: ignore[arg-type]
    ).all()
    if not students:
        raise HTTPException(
            status_code=422,
            detail="课堂还没有学生，发布后无人可作答；请先让学生进入课堂",
        )
    # 纯听音任务：无标准音的词既不能听也不能走看义（快照题型只有 audio），
    # 发布前拦下；混合题型不受限（无音词回落看义）
    if prompt_types == ["audio"]:
        missing_audio = [w.headword for w in words if not w.audio_url]
        if missing_audio:
            raise HTTPException(
                status_code=422,
                detail=f"纯听音任务要求每个词都有标准音（{len(missing_audio)} 个缺少，"
                "如 {0}）；请先上传音频，或同时勾选看义拼词".format(
                    "、".join(missing_audio[:3])
                ),
            )

    assignment_title = (title or "词汇练习").strip() or "词汇练习"
    snapshots = [build_word_snapshot(w, prompt_types) for w in words]

    # 同一课堂并发发布时锁住课堂行，避免版本号互撞或归档竞态
    # （与练习模块 publish_exercise 同口径）
    from app.models import Classroom

    session.exec(
        select(Classroom).where(Classroom.id == classroom_id).with_for_update()
    ).first()

    assignment = VocabularyAssignment(
        classroom_id=classroom_id,
        created_by=created_by,
        title=assignment_title,
        mode=mode,
        prompt_types=prompt_types,
        snapshot_items=snapshots,
        version_no=next_assignment_version(session, classroom_id),
        status="published",
        due_at=due_at,
    )
    session.add(assignment)
    session.flush()

    # 归档旧的 published（同一课堂同时只有一个进行中任务）
    for previous in session.exec(
        select(VocabularyAssignment).where(
            VocabularyAssignment.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularyAssignment.status == "published",
        )
    ).all():
        if previous.id == assignment.id:
            continue
        previous.status = "archived"
        previous.archived_at = get_datetime_utc()
        session.add(previous)

    # 目标名单 = 发布时的全班学生（完成率分母固定）
    for student in students:
        session.add(
            VocabularyAssignmentTarget(
                assignment_id=assignment.id, student_id=student.id
            )
        )
    session.commit()
    session.refresh(assignment)
    return assignment


def archive_assignment(session: Session, assignment: VocabularyAssignment) -> None:
    assignment.status = "archived"
    assignment.archived_at = get_datetime_utc()
    session.add(assignment)
    session.commit()


def ensure_assignment_open(assignment: VocabularyAssignment) -> None:
    """作答门禁：任务在发布中且未到截止时间（截止以服务器时间为准）。

    已开始的练习不因截止中断历史数据——只是不再接受新的会话与作答。
    """
    if assignment.status != "published":
        raise HTTPException(status_code=422, detail="该任务已结束，不能继续作答")
    if assignment.due_at is not None and datetime.now(UTC) >= assignment.due_at:
        raise HTTPException(status_code=422, detail="该任务已到截止时间，不能再作答")


def student_targeted(
    session: Session, assignment: VocabularyAssignment, student_id: uuid.UUID
) -> bool:
    return (
        session.exec(
            select(VocabularyAssignmentTarget).where(
                VocabularyAssignmentTarget.assignment_id == assignment.id,  # type: ignore[arg-type]
                VocabularyAssignmentTarget.student_id == student_id,  # type: ignore[arg-type]
            )
        ).first()
        is not None
    )


def get_or_create_session(
    session: Session,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    assignment: VocabularyAssignment,
) -> VocabularySession:
    """练习会话幂等创建：一个学生一个任务一份会话，中断续做。"""
    existing = session.exec(
        select(VocabularySession).where(
            VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
        )
    ).first()
    if existing is not None:
        return existing
    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=assignment.id,
        mode=assignment.mode,
    )
    session.add(vocab_session)
    try:
        session.commit()
    except Exception:
        session.rollback()
        existing = session.exec(
            select(VocabularySession).where(
                VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            )
        ).first()
        if existing is not None:
            return existing
        raise
    session.refresh(vocab_session)
    return vocab_session


def answers_by_item(
    session: Session, session_id: uuid.UUID
) -> dict[int, list[VocabularyAnswer]]:
    """会话内按题号分组的作答（含全部尝试，时间序）。"""
    grouped: dict[int, list[VocabularyAnswer]] = {}
    for answer in session.exec(
        select(VocabularyAnswer)
        .where(VocabularyAnswer.session_id == session_id)  # type: ignore[arg-type]
        .order_by(col(VocabularyAnswer.attempt_no))
    ).all():
        grouped.setdefault(answer.item_index, []).append(answer)
    return grouped


def first_answers_by_session(
    session: Session, session_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[int, VocabularyAnswer]]:
    """多会话的首答（attempt_no=1）矩阵：统计与错词本的口径。"""
    result: dict[uuid.UUID, dict[int, VocabularyAnswer]] = {}
    if not session_ids:
        return result
    for answer in session.exec(
        select(VocabularyAnswer).where(
            col(VocabularyAnswer.session_id).in_(session_ids),  # type: ignore[operator]
            VocabularyAnswer.attempt_no == 1,
        )
    ).all():
        result.setdefault(answer.session_id, {})[answer.item_index] = answer
    return result


def submit_answer(
    session: Session,
    vocab_session: VocabularySession,
    assignment: VocabularyAssignment,
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
) -> VocabularyAnswer:
    """判分与落库：幂等键重放返回原作答；练习允许重试（attempt_no 递增）。

    幂等键绑定会话与题号：命中其它会话/题目的键属于客户端误用，按 422
    拒绝（避免把别人的旧作答当成当前学生的提交返回）。
    """
    if idempotency_key:
        existing = session.exec(
            select(VocabularyAnswer).where(
                VocabularyAnswer.idempotency_key == idempotency_key  # type: ignore[arg-type]
            )
        ).first()
        if existing is not None:
            if (
                existing.session_id != vocab_session.id
                or existing.item_index != item_index
            ):
                raise HTTPException(
                    status_code=422,
                    detail="幂等键已用于其他作答，请刷新后重新提交",
                )
            return existing

    if not 0 <= item_index < len(assignment.snapshot_items):
        raise HTTPException(status_code=422, detail="题目序号不在本任务范围内")
    if prompt_type not in VOCAB_PROMPT_TYPES:
        raise HTTPException(status_code=422, detail=f"未知出题方式：{prompt_type}")
    snapshot_item = assignment.snapshot_items[item_index]
    item_prompt_types = snapshot_item.get("prompt_types")
    if isinstance(item_prompt_types, list) and prompt_type not in item_prompt_types:
        raise HTTPException(status_code=422, detail="该题不支持这种出题方式")

    normalized = normalize_spelling(answer_raw)
    if not normalized:
        raise HTTPException(status_code=422, detail="作答内容不能为空白")
    is_correct = check_spelling(answer_raw, snapshot_item)

    existing_attempts = session.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == vocab_session.id,  # type: ignore[arg-type]
            VocabularyAnswer.item_index == item_index,
        )
    ).all()
    attempt_no = len(existing_attempts) + 1

    answer = VocabularyAnswer(
        session_id=vocab_session.id,
        item_index=item_index,
        attempt_no=attempt_no,
        prompt_type=prompt_type,
        answer_raw=answer_raw[:255],
        answer_normalized=normalized[:255],
        is_correct=is_correct,
        word_id=uuid.UUID(str(snapshot_item["word_id"])),
        headword=str(snapshot_item["headword"])[:64],
        meaning_zh=str(snapshot_item["meaning_zh"])[:255],
        idempotency_key=idempotency_key,
    )
    session.add(answer)
    try:
        session.commit()
    except Exception:
        # 并发同幂等键：唯一索引兜底，重放返回既有作答
        session.rollback()
        if idempotency_key:
            existing = session.exec(
                select(VocabularyAnswer).where(
                    VocabularyAnswer.idempotency_key == idempotency_key  # type: ignore[arg-type]
                )
            ).first()
            if existing is not None:
                return existing
        raise
    session.refresh(answer)

    # 全部题至少答过一次 → 会话完成（练习重试不回退状态）
    answered_slots = {
        a.item_index
        for a in session.exec(
            select(VocabularyAnswer).where(
                VocabularyAnswer.session_id == vocab_session.id  # type: ignore[arg-type]
            )
        ).all()
    }
    if vocab_session.status == "in_progress" and answered_slots == set(
        range(len(assignment.snapshot_items))
    ):
        vocab_session.status = "submitted"
        vocab_session.submitted_at = get_datetime_utc()
        session.add(vocab_session)
        session.commit()
    return answer


def session_progress(
    session: Session, vocab_session: VocabularySession
) -> tuple[int, int]:
    """（已答题数, 首答正确数）。"""
    firsts = first_answers_by_session(session, [vocab_session.id]).get(
        vocab_session.id, {}
    )
    return len(firsts), sum(1 for a in firsts.values() if a.is_correct)


def class_results(
    session: Session, assignment: VocabularyAssignment
) -> tuple[list, list]:
    """按目标名单聚合：学生行（含未开始）+ 逐词错误分布（首答口径）。"""
    from app.models import (
        VocabularyStudentResultRow,
        VocabularyWordMisspelling,
        VocabularyWordStatRow,
    )

    targets = session.exec(
        select(VocabularyAssignmentTarget, Student)
        .join(Student, Student.id == VocabularyAssignmentTarget.student_id)  # ty: ignore[invalid-argument-type]
        .where(VocabularyAssignmentTarget.assignment_id == assignment.id)  # type: ignore[arg-type]
        .order_by(col(Student.display_name))
    ).all()

    sessions_by_student: dict[uuid.UUID, VocabularySession] = {}
    if targets:
        for vs in session.exec(
            select(VocabularySession).where(
                VocabularySession.assignment_id == assignment.id  # type: ignore[arg-type]
            )
        ).all():
            sessions_by_student[vs.student_id] = vs
    firsts = first_answers_by_session(
        session, [vs.id for vs in sessions_by_student.values()]
    )

    student_rows: list[VocabularyStudentResultRow] = []
    word_firsts: dict[int, list[VocabularyAnswer]] = {}
    for _target, student in targets:
        vocab_session = sessions_by_student.get(student.id)
        item_firsts = firsts.get(vocab_session.id, {}) if vocab_session else {}
        for idx, answer in item_firsts.items():
            word_firsts.setdefault(idx, []).append(answer)
        answered = len(item_firsts)
        correct = sum(1 for a in item_firsts.values() if a.is_correct)
        total = len(assignment.snapshot_items)
        status = (
            "not_started"
            if answered == 0
            else "completed"
            if answered >= total
            else "in_progress"
        )
        student_rows.append(
            VocabularyStudentResultRow(
                student_id=student.id,
                display_name=student.display_name,
                suffix=student.suffix,
                status=status,
                answered_count=answered,
                correct_first_count=correct,
                total_count=total,
                submitted_at=vocab_session.submitted_at if vocab_session else None,
            )
        )

    word_rows: list[VocabularyWordStatRow] = []
    for idx, snapshot_item in enumerate(assignment.snapshot_items):
        answers = word_firsts.get(idx, [])
        correct = sum(1 for a in answers if a.is_correct)
        wrong = [a for a in answers if not a.is_correct]
        misspelling_counter = Counter(a.answer_normalized for a in wrong)
        misspellings = [
            VocabularyWordMisspelling(answer=answer, count=count)
            for answer, count in misspelling_counter.most_common(5)
        ]
        word_rows.append(
            VocabularyWordStatRow(
                item_index=idx,
                word_id=uuid.UUID(str(snapshot_item["word_id"])),
                headword=str(snapshot_item["headword"]),
                meaning_zh=str(snapshot_item["meaning_zh"]),
                answered_count=len(answers),
                correct_first_count=correct,
                error_count=len(wrong),
                misspellings=misspellings,
            )
        )
    return student_rows, word_rows


def wrong_words(session: Session, student_id: uuid.UUID) -> list:
    """错词本：该学生全部词汇会话里首答判错的词（跨任务聚合，快照内容展示）。"""
    from app.models import VocabularyWrongWordItem

    firsts = session.exec(
        select(VocabularyAnswer)
        .join(
            VocabularySession,
            VocabularySession.id == VocabularyAnswer.session_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            VocabularyAnswer.attempt_no == 1,
            VocabularyAnswer.is_correct.is_(False),  # ty: ignore[unresolved-attribute]
        )
        .order_by(col(VocabularyAnswer.answered_at))
    ).all()
    by_word: dict[uuid.UUID, VocabularyWrongWordItem] = {}
    for answer in firsts:
        item = by_word.get(answer.word_id)
        if item is None:
            by_word[answer.word_id] = VocabularyWrongWordItem(
                word_id=answer.word_id,
                headword=answer.headword,
                meaning_zh=answer.meaning_zh,
                wrong_count=1,
                last_wrong_at=answer.answered_at,
            )
        else:
            item.wrong_count += 1
            if answer.answered_at and (
                item.last_wrong_at is None or answer.answered_at > item.last_wrong_at
            ):
                item.last_wrong_at = answer.answered_at
    return sorted(by_word.values(), key=lambda i: (-i.wrong_count, i.headword))
