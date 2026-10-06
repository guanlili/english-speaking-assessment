"""词汇学习域逻辑：判分规范化、发布快照、会话/作答状态机、统计聚合。

路由层（api/routes/vocabulary.py）只做参数与权限，业务不变量在这里：
- 判分确定性：Unicode NFKC + 去首尾空白 + casefold，只接受快照里的
  标准拼写与显式配置的变体，不调用大模型。
- 快照不可变：发布时深拷贝词条内容；词库后续编辑不改变进行中任务
  与历史报告。
- 统计口径：教师统计与错词本默认看首答（attempt_no=1），练习重试
  不冲高正确率；零作答显示 not_started 而非 0%。
"""

import random
import unicodedata
import uuid
from collections import Counter
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    SELF_PRACTICE_MAX_WORDS,
    SELF_PRACTICE_MIX_WRONG_RATIO,
    VOCAB_PROMPT_TYPES,
    Student,
    User,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentPublic,
    VocabularyAssignmentTarget,
    VocabularyBook,
    VocabularyBookItem,
    VocabularySession,
    VocabularyStudentAssignment,
    VocabularyStudentHistoryRow,
    VocabularyStudentResultRow,
    VocabularyStudentRoundRow,
    VocabularyTeacherAssignmentRow,
    VocabularyWord,
    VocabularyWrongWordItem,
    get_datetime_utc,
)
from app.services import vocab_quiz
from app.services.vocab_quiz import DEFAULT_PASS_LINE

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
    opens_at: datetime | None = None,
    duration_minutes: int | None = None,
    pass_line: int = DEFAULT_PASS_LINE,
) -> VocabularyAssignment:
    """发布：快照写入、目标名单固化，同一事务内完成。

    多任务并存：新发布不归档其他任务（教师可手动结束单个任务）。
    quiz = 限时测验：时长/开放/截止/及格线与听音题源校验收口在
    vocab_quiz.validate_quiz_publish；练习模式不接受考试时长。
    """
    if not words:
        raise HTTPException(status_code=422, detail="词汇任务至少需要一个词")
    if len(words) > MAX_TASK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"一次发布最多 {MAX_TASK_WORDS} 个词"
        )
    if mode not in {"practice", "quiz"}:
        raise HTTPException(status_code=422, detail="未知任务模式")
    if due_at is not None and due_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="截止时间必须晚于现在")
    if mode == "quiz":
        vocab_quiz.validate_quiz_publish(
            duration_minutes=duration_minutes,
            pass_line=pass_line,
            opens_at=opens_at,
            due_at=due_at,
            prompt_types=prompt_types,
            words_have_audio=all(w.audio_url for w in words),
        )
    elif duration_minutes is not None:
        raise HTTPException(
            status_code=422, detail="考试时长只用于测验模式（练习任务不需要）"
        )
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

    # 同一课堂并发发布时锁住课堂行，避免版本号互撞
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
        opens_at=opens_at,
        duration_minutes=duration_minutes if mode == "quiz" else None,
        pass_line=pass_line if mode == "quiz" else DEFAULT_PASS_LINE,
    )
    session.add(assignment)
    session.flush()

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
    """作答门禁：任务在发布中、已开放且未到截止时间（服务器时间口径）。

    已开始的练习不因截止中断历史数据——只是不再接受新的会话与作答。
    """
    if assignment.status != "published":
        raise HTTPException(status_code=422, detail="该任务已结束，不能继续作答")
    if assignment.opens_at is not None and datetime.now(UTC) < assignment.opens_at:
        raise HTTPException(status_code=422, detail="该任务尚未开放，不能作答")
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


def _assignment_sort_key(a: VocabularyAssignment) -> tuple:
    """任务排序：有截止升序在前，无截止按发布倒序在后。"""
    return (a.due_at is None, a.due_at.timestamp() if a.due_at else 0.0, -a.version_no)


def progress_of_round1(total: int, item_firsts: dict[int, VocabularyAnswer]) -> str:
    """任务进度状态机（锁定首轮首答）：not_started / in_progress / completed。"""
    answered = len(item_firsts)
    if answered == 0:
        return "not_started"
    return "completed" if answered >= total else "in_progress"


def is_overdue(assignment: VocabularyAssignment, progress: str) -> bool:
    """逾期与进度两维独立：过了截止且任务未完成才算逾期。"""
    return (
        assignment.due_at is not None
        and datetime.now(UTC) > assignment.due_at
        and (progress != "completed")
    )


def student_assignment_rows(
    session: Session, classroom_id: uuid.UUID, student_id: uuid.UUID
) -> list[VocabularyStudentAssignment]:
    """学生名单内全部任务（含已结束）的摘要行，按 due 升序、无 due 发布倒序。

    进度锁定首轮首答；round_count 含复习轮。
    """
    assignments = [
        a
        for a, _t in session.exec(
            select(VocabularyAssignment, VocabularyAssignmentTarget)
            .join(
                VocabularyAssignmentTarget,
                VocabularyAssignmentTarget.assignment_id == VocabularyAssignment.id,  # ty: ignore[invalid-argument-type]
            )
            .where(
                VocabularyAssignment.classroom_id == classroom_id,  # type: ignore[arg-type]
                VocabularyAssignmentTarget.student_id == student_id,  # type: ignore[arg-type]
            )
        ).all()
    ]
    rounds_by_assignment: dict[uuid.UUID, list[VocabularySession]] = {}
    if assignments:
        for vs in session.exec(
            select(VocabularySession).where(
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
                col(VocabularySession.assignment_id).in_(  # type: ignore[operator]
                    [a.id for a in assignments]
                ),
            )
        ).all():
            if vs.assignment_id is None:
                continue
            rounds_by_assignment.setdefault(vs.assignment_id, []).append(vs)
    all_round_ids = [vs.id for rounds in rounds_by_assignment.values() for vs in rounds]
    firsts = first_answers_by_session(session, all_round_ids)

    rows: list[VocabularyStudentAssignment] = []
    for assignment in sorted(assignments, key=_assignment_sort_key):
        rounds = sorted(
            rounds_by_assignment.get(assignment.id, []),
            key=lambda r: r.round_no,
        )
        first_round = rounds[0] if rounds else None
        item_firsts = firsts.get(first_round.id, {}) if first_round else {}
        progress = progress_of_round1(len(assignment.snapshot_items), item_firsts)
        is_quiz = assignment.mode == "quiz"
        if is_quiz:
            # 测验进度按答卷终结状态（不按答题完成度）：未参加/进行中/已终结
            quiz_rounds = [r for r in rounds if r.quiz_started_at is not None]
            if not quiz_rounds:
                progress = "not_started"
            elif any(r.status == "in_progress" for r in quiz_rounds):
                progress = "in_progress"
            else:
                progress = "completed"
        # 答案可见规则：测验成绩未公布时不下发正确数（前端隐藏成绩维度）
        masked = is_quiz and assignment.grades_published_at is None
        rows.append(
            VocabularyStudentAssignment(
                assignment_id=assignment.id,
                title=assignment.title,
                word_count=len(assignment.snapshot_items),
                due_at=assignment.due_at,
                progress=progress,
                overdue=is_overdue(assignment, progress),
                answered_count=len(item_firsts),
                correct_first_count=0
                if masked
                else sum(1 for a in item_firsts.values() if a.is_correct),
                round_count=len(rounds),
                masked=masked,
                is_quiz=is_quiz,
            )
        )
    return rows


def focused_assignment(
    session: Session, classroom_id: uuid.UUID, student_id: uuid.UUID
) -> VocabularyAssignment | None:
    """学生聚焦任务（多任务并存时的默认选中）：名单内进行中任务里
    最早截止的未完成者；全部完成（或无未完成）则最近发布的进行中任务。
    """
    targeted = session.exec(
        select(VocabularyAssignment)
        .join(
            VocabularyAssignmentTarget,
            VocabularyAssignmentTarget.assignment_id == VocabularyAssignment.id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            VocabularyAssignment.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularyAssignmentTarget.student_id == student_id,  # type: ignore[arg-type]
            VocabularyAssignment.status == "published",
        )
    ).all()
    if not targeted:
        return None
    rows = {
        r.assignment_id: r
        for r in student_assignment_rows(session, classroom_id, student_id)
    }
    unfinished = [
        a for a in targeted if rows.get(a.id) and rows[a.id].progress != "completed"
    ]
    pool = unfinished or list(targeted)
    pool.sort(key=_assignment_sort_key)
    return pool[0]


def get_or_create_session(
    session: Session,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    assignment: VocabularyAssignment,
    round_request: str | None = None,
) -> VocabularySession:
    """轮次幂等解析：续做未结束轮；只有显式 round="new" 才能新建轮次。

    - 未结束轮存在（同任务至多一个）：任何请求都返回它——重复点击/并发
      开练不会产生重复轮次；
    - 无任何轮次（首次开练）：开 round_no=1；
    - 全部轮次已结束：round="new"（「再练一轮」）开 max+1 复习轮；
      round="continue"/缺省 **不新建**（422）——继续/恢复绝不偷偷增加轮次，
      防止旧客户端或重复请求意外产生新轮。
    并发由唯一索引 (assignment_id, student_id, round_no) 兜底。
    首轮成绩锁定 round_no=1。
    """
    existing_rounds = session.exec(
        select(VocabularySession)
        .where(
            VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
        )
        .order_by(col(VocabularySession.round_no).desc())
    ).all()
    unfinished = next((r for r in existing_rounds if r.status == "in_progress"), None)
    if unfinished is not None:
        return unfinished
    if existing_rounds and round_request != "new":
        raise HTTPException(
            status_code=422,
            detail="没有进行中的轮次；请开始新的复习轮",
        )
    next_round_no = (existing_rounds[0].round_no if existing_rounds else 0) + 1
    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=assignment.id,
        mode=assignment.mode,
        round_no=next_round_no,
    )
    session.add(vocab_session)
    try:
        session.commit()
    except Exception:
        # 并发开练撞唯一索引：回滚后重查，返回赢家轮次
        session.rollback()
        again = session.exec(
            select(VocabularySession)
            .where(
                VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            )
            .order_by(col(VocabularySession.round_no).desc())
        ).all()
        unfinished = next((r for r in again if r.status == "in_progress"), None)
        if unfinished is not None:
            return unfinished
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


def session_snapshot(
    session: Session, vocab_session: VocabularySession
) -> list[dict[str, object]]:
    """轮次题单统一解析：任务轮读任务快照，自主/复习轮读自身固化题单。

    自主轮的题单在创建时固定并存在会话上，词库后续编辑与归档都不影响
    进行中的一轮；任务轮沿发布快照口径不变。
    """
    if vocab_session.assignment_id is not None:
        assignment = session.get(VocabularyAssignment, vocab_session.assignment_id)
        if assignment is None:
            raise HTTPException(status_code=422, detail="会话没有绑定任务，不能作答")
        return assignment.snapshot_items
    if not vocab_session.snapshot_items:
        raise HTTPException(status_code=422, detail="会话没有可作答的题单")
    return vocab_session.snapshot_items


def submit_answer(
    session: Session,
    vocab_session: VocabularySession,
    snapshot_items: list[dict[str, object]],
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
    one_attempt_per_item: bool = False,
) -> VocabularyAnswer:
    """判分与落库：幂等键重放返回原作答；练习允许重试（attempt_no 递增）。

    幂等键绑定会话与题号：命中其它会话/题目的键属于客户端误用，按 422
    拒绝（避免把别人的旧作答当成当前学生的提交返回）。
    题单由 session_snapshot 统一解析（任务快照或自主轮固化题单）。
    one_attempt_per_item（测验口径）：同题第二次提交 422；断网重传走
    幂等键重放，不受一次性限制误伤。
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

    if not 0 <= item_index < len(snapshot_items):
        raise HTTPException(status_code=422, detail="题目序号不在本任务范围内")
    if prompt_type not in VOCAB_PROMPT_TYPES:
        raise HTTPException(status_code=422, detail=f"未知出题方式：{prompt_type}")
    snapshot_item = snapshot_items[item_index]
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
    if one_attempt_per_item and existing_attempts:
        # 测验每题一次；能走到这里说明不是幂等键重放（前面已返回原作答）
        raise HTTPException(
            status_code=422, detail="测验每题只能作答一次，不能修改答案"
        )
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
        # 并发同幂等键：唯一索引兜底，重放返回既有作答。
        # 回退命中同样要过归属校验——并发里另一会话/题目先落库时，
        # 不能把别人的判分结果混进当前请求的回包。
        session.rollback()
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
        raise
    session.refresh(answer)

    # 全部题至少答过一次 → 会话完成（练习重试不回退状态）。
    # 测验不自动交卷：只有主动交卷或到时结算两种终结方式
    # （end_reason 由 submit_quiz_session / settle_due_sessions 落）。
    if not one_attempt_per_item:
        answered_slots = {
            a.item_index
            for a in session.exec(
                select(VocabularyAnswer).where(
                    VocabularyAnswer.session_id == vocab_session.id  # type: ignore[arg-type]
                )
            ).all()
        }
        if vocab_session.status == "in_progress" and answered_slots == set(
            range(len(snapshot_items))
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


def assignment_public(assignment: VocabularyAssignment) -> VocabularyAssignmentPublic:
    """任务对外快照字段（学生/教师共用）。"""
    return VocabularyAssignmentPublic(
        id=assignment.id,
        classroom_id=assignment.classroom_id,
        title=assignment.title,
        mode=assignment.mode,
        prompt_types=assignment.prompt_types,
        status=assignment.status,
        version_no=assignment.version_no,
        word_count=len(assignment.snapshot_items),
        due_at=assignment.due_at,
        opens_at=assignment.opens_at,
        duration_minutes=assignment.duration_minutes,
        pass_line=assignment.pass_line,
        grades_published_at=assignment.grades_published_at,
        answers_published_at=assignment.answers_published_at,
        published_at=assignment.published_at,
        archived_at=assignment.archived_at,
        created_by=assignment.created_by,
    )


def teacher_assignment_rows(
    session: Session, classroom_id: uuid.UUID
) -> list[VocabularyTeacherAssignmentRow]:
    """教师任务列表：名单进度汇总（首轮首答口径），按发布倒序。"""
    assignments = session.exec(
        select(VocabularyAssignment)
        .where(VocabularyAssignment.classroom_id == classroom_id)  # type: ignore[arg-type]
        .order_by(col(VocabularyAssignment.version_no).desc())
    ).all()
    if not assignments:
        return []
    # 按任务分组的轮次（含全部学生），首轮首答决定进度
    rounds_by_assignment: dict[uuid.UUID, list[VocabularySession]] = {}
    for vs in session.exec(
        select(VocabularySession).where(
            VocabularySession.classroom_id == classroom_id,  # type: ignore[arg-type]
            col(VocabularySession.assignment_id).in_([a.id for a in assignments]),  # type: ignore[operator]
        )
    ).all():
        if vs.assignment_id is not None:
            rounds_by_assignment.setdefault(vs.assignment_id, []).append(vs)
    all_round_ids = [vs.id for rounds in rounds_by_assignment.values() for vs in rounds]
    firsts = first_answers_by_session(session, all_round_ids)
    targets_by_assignment: dict[uuid.UUID, set[uuid.UUID]] = {}
    for target in session.exec(
        select(VocabularyAssignmentTarget).where(
            col(VocabularyAssignmentTarget.assignment_id).in_(  # type: ignore[operator]
                [a.id for a in assignments]
            )
        )
    ).all():
        targets_by_assignment.setdefault(target.assignment_id, set()).add(
            target.student_id
        )

    rows: list[VocabularyTeacherAssignmentRow] = []
    for assignment in assignments:
        total = len(assignment.snapshot_items)
        rounds_by_student: dict[uuid.UUID, list[VocabularySession]] = {}
        for vs in rounds_by_assignment.get(assignment.id, []):
            rounds_by_student.setdefault(vs.student_id, []).append(vs)
        counters = {"completed": 0, "in_progress": 0, "not_started": 0}
        overdue_count = 0
        for student_id in targets_by_assignment.get(assignment.id, set()):
            student_rounds = sorted(
                rounds_by_student.get(student_id, []), key=lambda r: r.round_no
            )
            item_firsts = firsts.get(student_rounds[0].id, {}) if student_rounds else {}
            progress = progress_of_round1(total, item_firsts)
            counters[progress] += 1
            if is_overdue(assignment, progress):
                overdue_count += 1
        rows.append(
            VocabularyTeacherAssignmentRow(
                assignment=assignment_public(assignment),
                target_count=len(targets_by_assignment.get(assignment.id, set())),
                completed_count=counters["completed"],
                in_progress_count=counters["in_progress"],
                not_started_count=counters["not_started"],
                overdue_count=overdue_count,
            )
        )
    return rows


def class_results(
    session: Session, assignment: VocabularyAssignment
) -> tuple[list, list]:
    """按目标名单聚合：学生行（含未开始）+ 逐词错误分布。

    练习：任务成绩锁定 round_no=1 的首答；复习轮只进 rounds 汇总。
    测验：先到时结算（不依赖学生在线），统计覆盖全部答卷的首答
    （错误分布含补考），学生行附成绩/及格/终结方式/切屏/补考授权；
    有效成绩默认取最好成绩（best）并按答卷明细可回溯。
    """
    from app.models import (
        VocabularyWordMisspelling,
        VocabularyWordStatRow,
    )

    is_quiz = assignment.mode == "quiz"
    if is_quiz:
        # 教师侧触碰即完成到时结算（结果不依赖学生页面在线）
        vocab_quiz.settle_due_sessions(session, assignment)

    targets = session.exec(
        select(VocabularyAssignmentTarget, Student)
        .join(Student, Student.id == VocabularyAssignmentTarget.student_id)  # ty: ignore[invalid-argument-type]
        .where(VocabularyAssignmentTarget.assignment_id == assignment.id)  # type: ignore[arg-type]
        .order_by(col(Student.display_name))
    ).all()

    rounds_by_student: dict[uuid.UUID, list[VocabularySession]] = {}
    if targets:
        for vs in session.exec(
            select(VocabularySession)
            .where(VocabularySession.assignment_id == assignment.id)  # type: ignore[arg-type]
            .order_by(col(VocabularySession.round_no))
        ).all():
            rounds_by_student.setdefault(vs.student_id, []).append(vs)
    all_rounds = [vs for rounds in rounds_by_student.values() for vs in rounds]
    firsts = first_answers_by_session(session, [vs.id for vs in all_rounds])

    def first_round(rounds: list[VocabularySession]) -> VocabularySession | None:
        # 存量数据迁移后恒有 round_no=1；防御性回落到最早轮
        return rounds[0] if rounds else None

    retake_by_student: dict[uuid.UUID, bool] = {
        target.student_id: target.retake_granted_at is not None
        for target, _student in targets
    }

    student_rows: list[VocabularyStudentResultRow] = []
    word_firsts: dict[int, list[VocabularyAnswer]] = {}
    for _target, student in targets:
        rounds = rounds_by_student.get(student.id, [])
        first_round_session = first_round(rounds)
        # 练习：统计锁定首轮首答；测验：覆盖全部答卷的首答（含补考）
        stat_rounds = (
            rounds
            if is_quiz
            else ([first_round_session] if first_round_session else [])
        )
        item_firsts: dict[int, VocabularyAnswer] = {}
        for stat_round in stat_rounds:
            # 同一题在多份答卷中取最好的一次首答（有效成绩口径）
            for idx, answer in (firsts.get(stat_round.id, {}) or {}).items():
                existing = item_firsts.get(idx)
                if existing is None or (not existing.is_correct and answer.is_correct):
                    item_firsts[idx] = answer
        for idx, answer in item_firsts.items():
            word_firsts.setdefault(idx, []).append(answer)
        answered = len(item_firsts)
        correct = sum(1 for a in item_firsts.values() if a.is_correct)
        total = len(assignment.snapshot_items)
        status = (
            "not_started"
            if answered == 0 and not rounds
            else "completed"
            if answered >= total
            else "in_progress"
        )
        if is_quiz:
            # 测验状态以答卷终结方式判定：全部答卷已终结 = completed
            latest = rounds[-1] if rounds else None
            if not rounds or all(r.quiz_started_at is None for r in rounds):
                status = "not_started"
            elif latest is not None and latest.status == "in_progress":
                status = "in_progress"
            else:
                status = "completed"
        quiz_rounds = [r for r in rounds if r.quiz_started_at is not None]
        best_score = None
        passed = None
        if is_quiz and quiz_rounds:
            best_score, passed, _attempts = vocab_quiz.effective_quiz_grade(
                session, assignment, student.id
            )
        round_rows = [
            VocabularyStudentRoundRow(
                round_no=vs.round_no,
                status=vs.status,
                answered_count=len(firsts.get(vs.id, {})),
                correct_first_count=sum(
                    1 for a in firsts.get(vs.id, {}).values() if a.is_correct
                ),
                submitted_at=vs.submitted_at,
                end_reason=vs.end_reason,
            )
            for vs in rounds
        ]
        student_rows.append(
            VocabularyStudentResultRow(
                student_id=student.id,
                display_name=student.display_name,
                suffix=student.suffix,
                status=status,
                answered_count=answered,
                correct_first_count=correct,
                total_count=total,
                submitted_at=(
                    first_round_session.submitted_at if first_round_session else None
                ),
                round_count=len(rounds),
                rounds=round_rows,
                quiz_end_reason=(quiz_rounds[-1].end_reason if quiz_rounds else None),
                score=best_score if is_quiz else None,
                passed=passed if is_quiz else None,
                tab_switch_count=sum(vs.tab_switch_count for vs in quiz_rounds)
                if is_quiz
                else 0,
                retake_granted=retake_by_student.get(student.id, False),
                attempt_count=len(quiz_rounds),
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


def wrong_word_items(
    session: Session,
    student_id: uuid.UUID,
    practiceable_ids: set[uuid.UUID] | None = None,
) -> list[VocabularyWrongWordItem]:
    """错词本聚合：该学生全部词汇轮次里首答判错的词（跨任务/自主聚合）。

    测验答卷在教师公布答案之前不进错词本（答案可见规则：提前收录等于
    泄露对错）；公布后照常收录。练习与自主/复习轮不受影响。

    先聚合完整作答证据，再筛出进入错词本的词（评审口径：一个词在首次
    判错之前的答对记录同样算「最近练对」证据，不能只看进本之后的）：
    - wrong_count 只统计独立首答（attempt_no=1）判错次数，一次答对不删除
      错词、不冲抵历史错误次数；
    - last_first_* 是最近一次独立首答的时间与对错（复盘过的词显示已纠正
      的首答，历史错误次数保持不变）；
    - last_correct_at 是最近一次答对时间（任意尝试，含首次判错之前），
      仅作复习证据。
    practiceable_ids 传入时标注词条是否仍在可练范围（active 公共/本班库
    内的 active 词条）——归档只影响能否再练，不删历史错词。
    """
    answers = session.exec(
        select(VocabularyAnswer)
        .join(
            VocabularySession,
            VocabularySession.id == VocabularyAnswer.session_id,  # ty: ignore[invalid-argument-type]
        )
        .outerjoin(
            VocabularyAssignment,
            VocabularyAssignment.id == VocabularySession.assignment_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            # 答案可见规则：测验答卷在答案公布前不进错词本
            (col(VocabularySession.assignment_id).is_(None))  # type: ignore[union-attr]
            | (col(VocabularyAssignment.mode) != "quiz")  # type: ignore[operator]
            | col(VocabularyAssignment.answers_published_at).is_not(None),  # type: ignore[union-attr]
        )
        .order_by(col(VocabularyAnswer.answered_at), col(VocabularyAnswer.attempt_no))
    ).all()
    # 全量作答证据：每个词条最近一次答对时间（时间序遍历，后写覆盖先写）
    last_correct_at: dict[uuid.UUID, datetime] = {}
    for answer in answers:
        if answer.is_correct and answer.answered_at is not None:
            last_correct_at[answer.word_id] = answer.answered_at
    by_word: dict[uuid.UUID, VocabularyWrongWordItem] = {}
    for answer in answers:
        item = by_word.get(answer.word_id)
        if answer.attempt_no == 1 and answer.is_correct:
            # 首答就对：只给已在错词本的词更新「最近独立首答」证据
            if item is not None:
                item.last_first_at = answer.answered_at
                item.last_first_is_correct = True
            continue
        if answer.attempt_no == 1:
            # 独立首答判错：累计历史错误次数（只增不减）
            if item is None:
                item = by_word.setdefault(
                    answer.word_id,
                    VocabularyWrongWordItem(
                        word_id=answer.word_id,
                        headword=answer.headword,
                        meaning_zh=answer.meaning_zh,
                        wrong_count=0,
                    ),
                )
            item.wrong_count += 1
            item.last_wrong_at = answer.answered_at
            item.last_first_at = answer.answered_at
            item.last_first_is_correct = False
    items = sorted(by_word.values(), key=lambda i: (-i.wrong_count, i.headword))
    for item in items:
        item.last_correct_at = last_correct_at.get(item.word_id)
    if practiceable_ids is not None:
        for item in items:
            item.practiceable = item.word_id in practiceable_ids
    return items


def pos_by_word_ids(
    session: Session, word_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """词条当前词性（错词本展示补齐；首答快照未存词性，历史不回改）。"""
    if not word_ids:
        return {}
    rows = session.exec(
        select(VocabularyWord.id, VocabularyWord.part_of_speech).where(
            col(VocabularyWord.id).in_(word_ids)  # type: ignore[operator]
        )
    ).all()
    return dict(rows)


# ── 学生自主练习：词库浏览、开轮选题、历史报告 ─────────────────────


def student_book_ids(session: Session, classroom_id: uuid.UUID) -> set[uuid.UUID]:
    """学生可浏览/可练的词库 id：active 公共库 + active 本班库。"""
    rows = session.exec(
        select(VocabularyBook.id).where(
            VocabularyBook.status == "active",
            (VocabularyBook.scope == "public")  # type: ignore[operator]
            | (VocabularyBook.classroom_id == classroom_id),  # type: ignore[operator,arg-type]
        )
    ).all()
    return set(rows)


def student_practiceable_word_ids(
    session: Session, classroom_id: uuid.UUID
) -> set[uuid.UUID]:
    """当前可练词库（active 公共/本班库）内的 active 词条 id 集合。

    错词「能否再练」的口径：词条仍在至少一本可练词库里，且词条本身是
    active（已归档词条不进新复习轮）；词库/词条归档只影响能否再练，
    不删历史错词。
    """
    rows = session.exec(
        select(VocabularyBookItem.word_id)
        .join(
            VocabularyBook,
            VocabularyBook.id == VocabularyBookItem.book_id,  # ty: ignore[invalid-argument-type]
        )
        .join(
            VocabularyWord,
            VocabularyWord.id == VocabularyBookItem.word_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            VocabularyBook.status == "active",
            VocabularyWord.status == "active",
            (VocabularyBook.scope == "public")  # type: ignore[operator]
            | (VocabularyBook.classroom_id == classroom_id),  # type: ignore[operator,arg-type]
        )
    ).all()
    return set(rows)


def student_book_word_counts(
    session: Session, book_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """词库 active 词条计数（学生浏览口径：归档词不计入可练数）。"""
    if not book_ids:
        return {}
    from sqlmodel import func

    rows = session.exec(
        select(VocabularyBookItem.book_id, func.count())
        .join(
            VocabularyWord,
            VocabularyWord.id == VocabularyBookItem.word_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            col(VocabularyBookItem.book_id).in_(book_ids),  # type: ignore[operator]
            VocabularyWord.status == "active",
        )
        .group_by(col(VocabularyBookItem.book_id))
    ).all()
    return dict(rows)


def student_book_words(
    session: Session, book_id: uuid.UUID, search: str | None = None
) -> list[VocabularyWord]:
    """词库内 active 词条（按词库排序）；search 过滤拼写/中英释义（不区分大小写）。"""
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
    if search:
        needle = search.strip().casefold()
        if needle:
            words = [
                w
                for w in words
                if needle in w.headword.casefold()
                or needle in (w.meaning_zh or "").casefold()
                or needle in (w.meaning_en or "").casefold()
            ]
    return words


def create_student_session(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    kind: str,
    book_id: uuid.UUID | None,
    word_count: int,
    mix_wrong: bool,
) -> tuple[VocabularySession, str, int]:
    """学生自主开轮：self = 词库选题（可混错词），review = 错词专项。

    - 选题后题单与题序一次性固化在会话上，刷新/换端重进同一轮；
    - 未结束的同款轮次直接续做（重复点击/刷新不产生重复轮次）；
    - 词数不足按实际数量出题，混入错词按最近错误优先、词条 ID 去重
      （同形异义本就是独立词条，天然保留）。
    返回 (会话, 展示标题, 混入错词数)。
    """
    if kind not in ("self", "review"):
        raise HTTPException(status_code=422, detail="未知的自主练习类型")
    word_count = max(1, min(word_count, SELF_PRACTICE_MAX_WORDS))

    # 续做幂等：同学生同类型（self 另要求同词库）的未结束轮直接返回，
    # 忽略本次请求的词数/混词差异——刷新与重复点击不产生重复轮次
    resume_conditions = [
        VocabularySession.student_id == student_id,  # type: ignore[arg-type]
        VocabularySession.kind == kind,  # type: ignore[arg-type]
        VocabularySession.status == "in_progress",  # type: ignore[arg-type]
    ]
    if kind == "self":
        resume_conditions.append(VocabularySession.source_book_id == book_id)  # type: ignore[arg-type]
    resume = session.exec(select(VocabularySession).where(*resume_conditions)).first()
    if resume is not None:
        title = _student_session_title(session, resume)
        return resume, title, _snapshot_wrong_count(resume)

    if kind == "review":
        vocab_session, title, wrong_used = _build_review_session(
            session,
            classroom_id=classroom_id,
            student_id=student_id,
            word_count=word_count,
        )
    else:
        vocab_session, title, wrong_used = _build_self_session(
            session,
            classroom_id=classroom_id,
            student_id=student_id,
            book_id=book_id,
            word_count=word_count,
            mix_wrong=mix_wrong,
        )
    session.add(vocab_session)
    try:
        session.commit()
    except Exception:
        # 并发开轮撞部分唯一索引（uq_vocab_session_self_active /
        # uq_vocab_session_review_active）：回滚后重查，返回赢家轮次，
        # 保证并发请求也只产生一个进行中轮次
        session.rollback()
        winner = session.exec(
            select(VocabularySession).where(*resume_conditions)
        ).first()
        if winner is None:
            raise
        return (
            winner,
            _student_session_title(session, winner),
            _snapshot_wrong_count(winner),
        )
    session.refresh(vocab_session)
    return vocab_session, title, wrong_used


def _student_session_title(session: Session, vocab_session: VocabularySession) -> str:
    """轮次展示标题：任务轮用任务名，自主轮用词库名，复习轮固定文案。"""
    if vocab_session.assignment_id is not None:
        assignment = session.get(VocabularyAssignment, vocab_session.assignment_id)
        if assignment is not None:
            return assignment.title
    if vocab_session.source_book_id is not None:
        book = session.get(VocabularyBook, vocab_session.source_book_id)
        if book is not None:
            return book.title
    return "错词复习" if vocab_session.kind == "review" else "自主练习"


def _snapshot_wrong_count(vocab_session: VocabularySession) -> int:
    """固化题单里选自历史错词的词条数（混入占比报告用）。"""
    return sum(
        1
        for item in vocab_session.snapshot_items or []
        if item.get("from_wrong") is True
    )


def _self_snapshot_item(word: VocabularyWord, from_wrong: bool) -> dict[str, object]:
    """自主/复习轮的题单条目：任务快照结构 + from_wrong 标记。

    出题方式给看义+听音：无标准音的词沿用既有回落（听音仅在已答后开放，
    不为播放提前泄露未答拼写）。
    """
    item = build_word_snapshot(word, ["meaning", "audio"])
    item["from_wrong"] = from_wrong
    return item


def _build_self_session(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    book_id: uuid.UUID | None,
    word_count: int,
    mix_wrong: bool,
) -> tuple[VocabularySession, str, int]:
    """构建自主轮（不落库；提交与并发兜底在 create_student_session）。

    混错词补位规则：先按最近错误优先取目标数量的错词，再优先用非错词
    补足到目标词数（保证混入占比不超过目标）；非错词不足时才用其余错词
    补足，且这些词同样标记 from_wrong——题单标记与报告口径永远一致。
    """
    if book_id is None:
        raise HTTPException(status_code=422, detail="自主练习需要选择一个词库")
    book = session.get(VocabularyBook, book_id)
    if book is None or book.status != "active":
        raise HTTPException(status_code=404, detail="词库不存在或已归档")
    if book.id not in student_book_ids(session, classroom_id):
        raise HTTPException(status_code=403, detail="没有权限使用这个词库")
    words = student_book_words(session, book_id)
    if not words:
        raise HTTPException(status_code=422, detail="词库里没有可用词条")
    total = min(word_count, len(words))

    picked_wrong: list[VocabularyWord] = []
    wrong_pool_ids: set[uuid.UUID] = set()
    if mix_wrong:
        # 只取所选词库内的历史错词，最近错误优先；按词条 ID 去重
        book_word_ids = {w.id for w in words}
        wrong_pool = [
            item
            for item in wrong_word_items(session, student_id)
            if item.word_id in book_word_ids and item.last_wrong_at is not None
        ]
        wrong_pool.sort(
            key=lambda i: i.last_wrong_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )  # type: ignore[arg-type,operator]
        wrong_pool_ids = {item.word_id for item in wrong_pool}
        wrong_target = int(total * SELF_PRACTICE_MIX_WRONG_RATIO + 0.5)
        wanted = {item.word_id for item in wrong_pool[:wrong_target]}
        picked_wrong = [w for w in words if w.id in wanted]

    picked_ids = {w.id for w in picked_wrong}
    remaining = total - len(picked_wrong)
    # 优先非错词补位（普通词充足时混入占比恒 ≤ 目标）
    plain_fill = [
        w for w in words if w.id not in picked_ids and w.id not in wrong_pool_ids
    ][:remaining]
    extra_wrong: list[VocabularyWord] = []
    if len(plain_fill) < remaining:
        # 非错词不足：用其余错词补足，并同样计入错词标记
        extra_wrong = [
            w for w in words if w.id not in picked_ids and w.id in wrong_pool_ids
        ][: remaining - len(plain_fill)]
    items = picked_wrong + plain_fill + extra_wrong
    wrong_marked_ids = picked_ids | {w.id for w in extra_wrong}
    random.shuffle(items)  # 题序创建时一次性定死，本轮内不再变化

    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=None,
        kind="self",
        source_book_id=book_id,
        snapshot_items=[
            _self_snapshot_item(w, w.id in wrong_marked_ids) for w in items
        ],
        mix_wrong=mix_wrong,
        mode="practice",
        round_no=1,
    )
    return vocab_session, book.title, len(wrong_marked_ids)


def _build_review_session(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    word_count: int,
) -> tuple[VocabularySession, str, int]:
    """错词专项复习：限定当前可练词库内的历史错词，最近错误优先。

    可练口径 = 词库 active 且词条 active（已归档词条不进新复习轮，
    历史错词记录保留）。构建不落库；提交与并发兜底在 create_student_session。
    """
    practiceable_ids = student_practiceable_word_ids(session, classroom_id)
    pool = [
        item
        for item in wrong_word_items(session, student_id, practiceable_ids)
        if item.practiceable and item.last_wrong_at is not None
    ]
    pool.sort(
        key=lambda i: i.last_wrong_at or datetime.min.replace(tzinfo=UTC), reverse=True
    )  # type: ignore[arg-type,operator]
    pool = pool[:word_count]
    if not pool:
        raise HTTPException(status_code=422, detail="还没有可复习的错词")
    words = {
        w.id: w
        for w in session.exec(
            select(VocabularyWord).where(
                col(VocabularyWord.id).in_([i.word_id for i in pool]),  # type: ignore[operator]
                VocabularyWord.status == "active",
            )
        ).all()
    }
    items = [words[i.word_id] for i in pool if i.word_id in words]
    if not items:
        raise HTTPException(status_code=422, detail="还没有可复习的错词")
    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=None,
        kind="review",
        snapshot_items=[_self_snapshot_item(w, True) for w in items],
        mode="practice",
        round_no=1,
    )
    return vocab_session, "错词复习", len(items)


def student_plan(
    session: Session, vocab_session: VocabularySession, reveal: bool = False
) -> object:
    """自主轮/历史单次的作答视图：未答题不透露拼写，已答回填首答输入。

    任务轮同样支持（历史详情三类轮次统一入口）。
    测验答卷受公布规则约束：答案未公布 → 已答题也不揭示正确拼写与对错
    （first_answer 仍回填本人输入）；成绩未公布 → correct_first_count
    置 0 并打 masked 标记（前端隐藏成绩维度，不显示"首答 0"）。
    reveal=True（教师查看答卷）不受公布规则约束，全量揭示。
    """
    from app.models import VocabularyStudentItem, VocabularyStudentPlan

    assignment = (
        session.get(VocabularyAssignment, vocab_session.assignment_id)
        if vocab_session.assignment_id is not None
        else None
    )
    is_quiz = assignment is not None and assignment.mode == "quiz"
    if is_quiz and assignment is not None:
        # 触碰答卷即结算到时答卷（不依赖学生页面在线）
        vocab_quiz.settle_due_sessions(session, assignment)
        session.refresh(vocab_session)
    snapshot_items = session_snapshot(session, vocab_session)
    answers_visible = reveal or not (
        is_quiz and assignment is not None and assignment.answers_published_at is None
    )
    score_visible = reveal or not (
        is_quiz and assignment is not None and assignment.grades_published_at is None
    )
    grouped = answers_by_item(session, vocab_session.id)
    items: list[VocabularyStudentItem] = []
    answered_count = 0
    correct_first = 0
    for idx, snapshot_item in enumerate(snapshot_items):
        attempts = grouped.get(idx, [])
        first = next((a for a in attempts if a.attempt_no == 1), None)
        if first is not None:
            answered_count += 1
            if first.is_correct:
                correct_first += 1
        item_prompt_types = snapshot_item.get("prompt_types")
        audio_allowed = (
            isinstance(item_prompt_types, list)
            and "audio" in item_prompt_types
            and (snapshot_item.get("audio_url") is not None or first is not None)
        )
        items.append(
            VocabularyStudentItem(
                item_index=idx,
                prompt_type="audio" if audio_allowed else "meaning",
                part_of_speech=(
                    str(snapshot_item["part_of_speech"])
                    if snapshot_item.get("part_of_speech") is not None
                    else None
                ),
                meaning_zh=str(snapshot_item["meaning_zh"]),
                meaning_en=(
                    str(snapshot_item["meaning_en"])
                    if snapshot_item.get("meaning_en") is not None
                    else None
                ),
                audio_url=(
                    str(snapshot_item["audio_url"])
                    if snapshot_item.get("audio_url") is not None
                    else None
                ),
                # 未作答不透露拼写；测验答案未公布时已答也不揭示
                headword=(first.headword if first is not None else None)
                if answers_visible
                else None,
                answered=first is not None,
                is_correct=(first.is_correct if first is not None else None)
                if answers_visible
                else None,
                attempt_count=len(attempts),
                from_wrong=snapshot_item.get("from_wrong") is True,
                first_answer=first.answer_raw if first is not None else None,
            )
        )
    title = _student_session_title(session, vocab_session)
    deadline = None
    remaining = None
    if is_quiz and assignment is not None:
        deadline = vocab_quiz.quiz_deadline(vocab_session, assignment)
        if vocab_session.status == "in_progress" and deadline is not None:
            remaining = max(0, int((deadline - datetime.now(UTC)).total_seconds()))
    masked = is_quiz and not score_visible
    plan = VocabularyStudentPlan(
        session_id=vocab_session.id,
        kind=vocab_session.kind,
        status=vocab_session.status,
        title=title,
        book_id=vocab_session.source_book_id,
        round_no=(
            vocab_session.round_no if vocab_session.assignment_id is not None else None
        ),
        mix_wrong=vocab_session.mix_wrong,
        started_at=vocab_session.started_at,
        submitted_at=vocab_session.submitted_at,
        total_count=len(snapshot_items),
        answered_count=answered_count,
        correct_first_count=0 if masked else correct_first,
        items=items,
        is_quiz=is_quiz,
        end_reason=vocab_session.end_reason,
        deadline=deadline,
        remaining_seconds=remaining,
        answers_visible=answers_visible,
        score_visible=score_visible,
        masked=masked,
    )
    return plan


def history_rows(
    session: Session, student_id: uuid.UUID, limit: int = 50
) -> list[VocabularyStudentHistoryRow]:
    """练习历史（含任务轮/自主轮/复习轮），按开始时间倒序。

    正确率不在行内预计算：口径是 correct_first_count / answered_count
    （首答正确率分母为已答题数），零作答显示未作答，不画成 0%。
    """
    from app.models import VocabularyStudentHistoryRow as Row

    limit = max(1, min(limit, 200))
    rounds = list(
        session.exec(
            select(VocabularySession)
            .where(VocabularySession.student_id == student_id)  # type: ignore[arg-type]
            .order_by(col(VocabularySession.started_at).desc())
            .limit(limit)
        ).all()
    )
    assignment_ids = [r.assignment_id for r in rounds if r.assignment_id is not None]
    assignments: dict[uuid.UUID, VocabularyAssignment] = {}
    if assignment_ids:
        assignments = {
            a.id: a
            for a in session.exec(
                select(VocabularyAssignment).where(
                    col(VocabularyAssignment.id).in_(assignment_ids)  # type: ignore[operator]
                )
            ).all()
        }
    firsts = first_answers_by_session(session, [r.id for r in rounds])
    rows: list[Row] = []
    for r in rounds:
        item_firsts = firsts.get(r.id, {})
        assignment = assignments.get(r.assignment_id) if r.assignment_id else None
        if r.assignment_id is not None:
            title = assignment.title if assignment else "词汇任务"
            total = len(assignment.snapshot_items) if assignment else 0
        else:
            title = _student_session_title(session, r)
            total = len(r.snapshot_items or [])
        is_quiz = assignment is not None and assignment.mode == "quiz"
        # 测验结算不依赖学生在线：触碰历史时把到时答卷收口
        if is_quiz and r.status == "in_progress" and assignment is not None:
            vocab_quiz.settle_due_sessions(session, assignment)
            session.refresh(r)
        # 答案可见规则：测验成绩未公布 → 只下发提交状态（correct 置 0 +
        # masked 标记，前端隐藏成绩维度，不显示"首答 0"）
        masked = (
            is_quiz
            and assignment is not None
            and (assignment.grades_published_at is None)
        )
        rows.append(
            Row(
                session_id=r.id,
                kind=r.kind,
                title=title,
                status=r.status,
                round_no=r.round_no if r.assignment_id is not None else None,
                total_count=total,
                answered_count=len(item_firsts),
                correct_first_count=0
                if masked
                else sum(1 for a in item_firsts.values() if a.is_correct),
                started_at=r.started_at,
                submitted_at=r.submitted_at,
                book_id=r.source_book_id,
                assignment_id=r.assignment_id,
                masked=masked,
                is_quiz=is_quiz,
                end_reason=r.end_reason,
            )
        )
    return rows
