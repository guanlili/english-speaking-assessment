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
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.models import (
    SELF_PRACTICE_MAX_WORDS,
    SELF_PRACTICE_MIX_WRONG_RATIO,
    VOCAB_PROMPT_TYPES,
    Classroom,
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
    VocabularyStudentItem,
    VocabularyStudentPlan,
    VocabularyStudentResultRow,
    VocabularyStudentRoundRow,
    VocabularyTeacherAssignmentRow,
    VocabularyWord,
    VocabularyWordIn,
    VocabularyWordMisspelling,
    VocabularyWordStatRow,
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


def visible_book_ids_for(session: Session, user: User) -> set[uuid.UUID]:
    """教师可用的词库 id 集合：本校公共词库 + 自己名下的班级词库。

    多租户：谓词始终带本校过滤（他校词库在 RLS 激活环境本就不可见，
    这里是无 RLS 环境的应用层等价防线，CLAUDE.md 不变量④）。
    """
    rows = session.exec(
        select(VocabularyBook.id).where(
            VocabularyBook.tenant_id == user.tenant_id,
            (VocabularyBook.scope == "public")  # type: ignore[union-attr]
            | (VocabularyBook.owner_id == user.id),  # type: ignore[operator]
        )
    ).all()
    return set(rows)


def _publish_allowed_book_ids(session: Session, viewer: User) -> set[uuid.UUID]:
    """发布可用的词库 id 全集。

    管理员=本校全部词库（跨校他校词库不放行，与 RLS 激活环境对齐）；
    其余角色=本校公共库 + 本人班级库。
    """
    if viewer.role == "school_admin":
        return set(
            session.exec(
                select(VocabularyBook.id).where(
                    VocabularyBook.tenant_id == viewer.tenant_id
                )
            ).all()
        )
    return visible_book_ids_for(session, viewer)


def _publish_words_of_book(
    session: Session, book_id: uuid.UUID, allowed_book_ids: set[uuid.UUID]
) -> list[VocabularyWord]:
    """整本词库的发布词单：active 词、按 position 排序。"""
    book = session.get(VocabularyBook, book_id)
    if book is None or book.status != "active":
        raise HTTPException(status_code=404, detail="词库不存在或已归档")
    if book.id not in allowed_book_ids:
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


def _validate_word_id_list(word_ids: list[uuid.UUID]) -> None:
    """显式词清单的形态校验：非空、不超上限、无重复。"""
    if not word_ids:
        raise HTTPException(status_code=422, detail="需要指定词库或词清单")
    if len(word_ids) > MAX_TASK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"一次发布最多 {MAX_TASK_WORDS} 个词"
        )
    if len(set(word_ids)) != len(word_ids):
        raise HTTPException(status_code=422, detail="词清单内有重复词条")


def _load_publishable_words(
    session: Session, word_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VocabularyWord]:
    """按 id 载入词条；有不存在或已归档的整单 422，不静默缩水。"""
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
    return found


def _ensure_word_ownership(
    session: Session, word_ids: list[uuid.UUID], allowed_book_ids: set[uuid.UUID]
) -> None:
    """显式清单的归属核验：每个词必须出现在至少一本可见词库里。

    否则可借发布/结果接口读到其他教师私有词条的拼写与释义。
    """
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


def resolve_publish_words(
    session: Session,
    book_id: uuid.UUID | None,
    word_ids: list[uuid.UUID] | None,
    viewer: User,
) -> list[VocabularyWord]:
    """发布词单解析：整本词库（active 词、按 position）或显式词清单。

    权限：来源词库必须对发布教师可见（本校公共库或本人班级库；管理员=
    本校全部），显式 word_ids 的每个词也必须归属至少一本可见词库——否则可借
    发布/结果接口读到其他教师私有词条的拼写与释义。

    发布校验三口径：所选词数、可出题数、最终题数一致（题量不允许
    超过实际可出题量——清单里多余/归档词直接 422，避免静默缩水）。
    """
    allowed_book_ids = _publish_allowed_book_ids(session, viewer)
    if book_id is not None:
        return _publish_words_of_book(session, book_id, allowed_book_ids)

    word_ids = word_ids or []
    _validate_word_id_list(word_ids)
    found = _load_publishable_words(session, word_ids)
    _ensure_word_ownership(session, word_ids, allowed_book_ids)
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


def _validate_publish_params(
    words: list[VocabularyWord],
    prompt_types: list[str],
    mode: str,
    *,
    due_at: datetime | None,
    opens_at: datetime | None,
    duration_minutes: int | None,
    pass_line: int,
) -> None:
    """发布前全部参数校验：词量、模式、时间、测验规则、纯听音可出题性。"""
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


def _lock_classroom(session: Session, classroom_id: uuid.UUID) -> None:
    """同一课堂并发发布时锁住课堂行，避免版本号互撞。

    与练习模块 publish_exercise 同口径。
    """
    session.exec(
        select(Classroom).where(Classroom.id == classroom_id).with_for_update()
    ).first()


def _add_assignment_targets(
    session: Session, assignment: VocabularyAssignment, students: Sequence[Student]
) -> None:
    """目标名单 = 发布时的全班学生（完成率分母固定）。"""
    for student in students:
        session.add(
            VocabularyAssignmentTarget(
                assignment_id=assignment.id, student_id=student.id
            )
        )


def _require_classroom_students(
    session: Session, classroom_id: uuid.UUID
) -> list[Student]:
    """发布前置：课堂必须已有学生（否则发布了也无人可作答）。"""
    students = session.exec(
        select(Student).where(Student.classroom_id == classroom_id)  # type: ignore[arg-type]
    ).all()
    if not students:
        raise HTTPException(
            status_code=422,
            detail="课堂还没有学生，发布后无人可作答；请先让学生进入课堂",
        )
    return list(students)


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
    _validate_publish_params(
        words,
        prompt_types,
        mode,
        due_at=due_at,
        opens_at=opens_at,
        duration_minutes=duration_minutes,
        pass_line=pass_line,
    )
    students = _require_classroom_students(session, classroom_id)

    assignment_title = (title or "词汇练习").strip() or "词汇练习"
    snapshots = [build_word_snapshot(w, prompt_types) for w in words]

    _lock_classroom(session, classroom_id)

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
    _add_assignment_targets(session, assignment, students)
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


def _load_student_assignments(
    session: Session, classroom_id: uuid.UUID, student_id: uuid.UUID
) -> tuple[
    list[VocabularyAssignment],
    dict[uuid.UUID, list[VocabularySession]],
]:
    """名单内全部任务（含已结束）+ 每任务的轮次集合。"""
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
    return assignments, rounds_by_assignment


def _quiz_progress(rounds: list[VocabularySession]) -> str:
    """测验进度按答卷终结状态（不按答题完成度）：未参加/进行中/已终结。"""
    quiz_rounds = [r for r in rounds if r.quiz_started_at is not None]
    if not quiz_rounds:
        return "not_started"
    if any(r.status == "in_progress" for r in quiz_rounds):
        return "in_progress"
    return "completed"


def _student_assignment_row(
    assignment: VocabularyAssignment,
    rounds: list[VocabularySession],
    item_firsts: dict[int, VocabularyAnswer],
) -> VocabularyStudentAssignment:
    """单个任务的摘要行：进度、逾期、首答正确数、公布掩码。"""
    progress = _quiz_progress(rounds) if assignment.mode == "quiz" else None
    if progress is None:
        progress = progress_of_round1(len(assignment.snapshot_items), item_firsts)
    is_quiz = assignment.mode == "quiz"
    # 答案可见规则：测验成绩未公布时不下发正确数（前端隐藏成绩维度）
    masked = is_quiz and assignment.grades_published_at is None
    return VocabularyStudentAssignment(
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


def student_assignment_rows(
    session: Session, classroom_id: uuid.UUID, student_id: uuid.UUID
) -> list[VocabularyStudentAssignment]:
    """学生名单内全部任务（含已结束）的摘要行，按 due 升序、无 due 发布倒序。

    进度锁定首轮首答；round_count 含复习轮。
    """
    assignments, rounds_by_assignment = _load_student_assignments(
        session, classroom_id, student_id
    )
    # 进度只消费每任务首轮（round_no 最小）的首答，预取同样只取首轮
    first_round_ids = [
        min(rounds, key=lambda r: r.round_no).id
        for rounds in rounds_by_assignment.values()
        if rounds
    ]
    firsts = first_answers_by_session(session, first_round_ids)

    rows: list[VocabularyStudentAssignment] = []
    for assignment in sorted(assignments, key=_assignment_sort_key):
        rounds = sorted(
            rounds_by_assignment.get(assignment.id, []),
            key=lambda r: r.round_no,
        )
        first_round = rounds[0] if rounds else None
        item_firsts = firsts.get(first_round.id, {}) if first_round else {}
        rows.append(_student_assignment_row(assignment, rounds, item_firsts))
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


def _student_session_rounds(
    session: Session, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> list[VocabularySession]:
    """该学生在该任务下的全部轮次（按 round_no 倒序）。"""
    return list(
        session.exec(
            select(VocabularySession)
            .where(
                VocabularySession.assignment_id == assignment_id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            )
            .order_by(col(VocabularySession.round_no).desc())
        ).all()
    )


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
    existing_rounds = _student_session_rounds(session, assignment.id, student_id)
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
        again = _student_session_rounds(session, assignment.id, student_id)
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


def _min_round_by_student(
    rounds: list[VocabularySession],
) -> dict[uuid.UUID, VocabularySession]:
    """轮次列表里每个学生的首轮（round_no 最小；同号取先遍历到的）。"""
    first_by_student: dict[uuid.UUID, VocabularySession] = {}
    for vs in rounds:
        cur = first_by_student.get(vs.student_id)
        if cur is None or vs.round_no < cur.round_no:
            first_by_student[vs.student_id] = vs
    return first_by_student


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


MAX_NORMALIZED_ANSWER_LEN = 255


def _normalized_answer_or_422(answer_raw: str) -> str:
    """规范化作答并校验长度（返修R11）。

    原文 ≤255 不代表 NFKC 规范化后仍 ≤255（如 "ﬃ"×86 → 258 字符）。
    超限直接 422 拒绝——落库截断会让同载荷重放被判不匹配、不同载荷
    反而碰撞匹配。已有截断存量行不受影响（不回填不重算）。
    """
    normalized = normalize_spelling(answer_raw)
    if not normalized:
        raise HTTPException(status_code=422, detail="作答内容不能为空白")
    if len(normalized) > MAX_NORMALIZED_ANSWER_LEN:
        raise HTTPException(
            status_code=422,
            detail="作答内容过长（规范化后超过 255 字符），请缩短后提交",
        )
    return normalized


def recognize_answer_replay(
    session: Session,
    vocab_session: VocabularySession,
    *,
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
) -> VocabularyAnswer | None:
    """识别已成功的幂等提交（断网重传回执）。

    命中同会话+同题+同出题方式+同规范化答案 → 返回原作答：在截止/归档/
    交卷之后仍可取得成功确认，不新增答案。键被用于别会话/别题/别出题方式/
    不同答案 → 稳定 422（客户端误用，不得把旧作答当本次提交返回）。
    返回 None 表示无重放，调用方走正常门禁+落库。
    """
    if not idempotency_key:
        return None
    # 超限载荷不可能匹配任何存量行（落库均为完整规范化值），先按长度拒绝
    normalized = _normalized_answer_or_422(answer_raw)
    existing = session.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.idempotency_key == idempotency_key  # type: ignore[arg-type]
        )
    ).first()
    if existing is None:
        return None
    # 幂等键全局唯一（设计稿 §4.3）：跨租户命中按不存在处理——不泄露
    # 他校是否存在同键作答，也不会把他校回执当本次结果返回
    if existing.tenant_id != vocab_session.tenant_id:
        return None
    same = (
        existing.session_id == vocab_session.id
        and existing.item_index == item_index
        and existing.prompt_type == prompt_type
        and existing.answer_normalized == normalized
    )
    if not same:
        raise HTTPException(
            status_code=422, detail="幂等键已用于其他作答，请刷新后重新提交"
        )
    return existing


def _replay_or_none(
    session: Session,
    vocab_session: VocabularySession,
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
) -> VocabularyAnswer | None:
    """幂等键重放：命中则返回原作答，否则 None。

    3 处调用（锁前预检 / 锁内重查 / 约束冲突兜底）必须是同一份参数绑定，
    所以收成一个入口，避免哪一处写漏了参数。
    """
    return recognize_answer_replay(
        session,
        vocab_session,
        item_index=item_index,
        prompt_type=prompt_type,
        answer_raw=answer_raw,
        idempotency_key=idempotency_key,
    )


def _validate_answer_input(
    snapshot_items: list[dict[str, object]], item_index: int, prompt_type: str
) -> dict[str, object]:
    """校验题号与出题方式，返回该题快照项；不合法一律 422。"""
    if not 0 <= item_index < len(snapshot_items):
        raise HTTPException(status_code=422, detail="题目序号不在本任务范围内")
    if prompt_type not in VOCAB_PROMPT_TYPES:
        raise HTTPException(status_code=422, detail=f"未知出题方式：{prompt_type}")
    snapshot_item = snapshot_items[item_index]
    item_prompt_types = snapshot_item.get("prompt_types")
    if isinstance(item_prompt_types, list) and prompt_type not in item_prompt_types:
        raise HTTPException(status_code=422, detail="该题不支持这种出题方式")
    return snapshot_item


def _guard_quiz_timing(
    session: Session,
    vocab_session: VocabularySession,
    assignment: VocabularyAssignment | None,
    *,
    one_attempt_per_item: bool,
) -> None:
    """测验的锁内终态与到时门禁。

    统一锁内终态规则（返修R08）：先看终态——已 manual/submitted 的事实不得
    被改写成 timeout；仍 in_progress 才按锁内时间判超时。到时立即终结本答卷
    （与惰性结算同口径）后拒绝，成绩按截止时的作答计算。
    """
    if not (one_attempt_per_item and assignment is not None):
        return
    if vocab_session.status != "in_progress":
        raise HTTPException(status_code=422, detail="测验已交卷，不能继续作答")
    deadline = vocab_quiz.quiz_deadline(vocab_session, assignment)
    if deadline is not None and datetime.now(UTC) > deadline:
        vocab_session.status = "submitted"
        vocab_session.end_reason = "timeout"
        vocab_session.submitted_at = deadline
        session.add(vocab_session)
        session.commit()
        raise HTTPException(status_code=422, detail="测验时间已到，已自动交卷")


def _next_attempt_no(
    session: Session,
    vocab_session: VocabularySession,
    item_index: int,
    *,
    one_attempt_per_item: bool,
) -> int:
    """第几次作答；测验口径下同题第二次直接 422。"""
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
    return len(existing_attempts) + 1


def _build_answer(
    vocab_session: VocabularySession,
    snapshot_item: dict[str, object],
    *,
    item_index: int,
    attempt_no: int,
    prompt_type: str,
    answer_raw: str,
    normalized: str,
    is_correct: bool,
    idempotency_key: str | None,
) -> VocabularyAnswer:
    return VocabularyAnswer(
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


def _advance_practice_session(
    session: Session,
    vocab_session: VocabularySession,
    snapshot_items: list[dict[str, object]],
    item_index: int,
) -> None:
    """练习：全部题至少答过一次 → 会话完成（练习重试不回退状态）。

    测验不自动交卷：只有主动交卷或到时结算两种终结方式
    （end_reason 由 submit_quiz_session / settle_due_sessions 落）。
    """
    answered_slots = {
        a.item_index
        for a in session.exec(
            select(VocabularyAnswer).where(
                VocabularyAnswer.session_id == vocab_session.id  # type: ignore[arg-type]
            )
        ).all()
    } | {item_index}
    if vocab_session.status == "in_progress" and answered_slots == set(
        range(len(snapshot_items))
    ):
        vocab_session.status = "submitted"
    vocab_session.submitted_at = get_datetime_utc()
    session.add(vocab_session)


def _commit_or_resolve_conflict(
    session: Session,
    vocab_session: VocabularySession,
    *,
    one_attempt_per_item: bool,
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
) -> VocabularyAnswer | None:
    """提交并兜底并发冲突；若判定为幂等重放则返回原作答。

    行锁下正常不会撞约束；兜底绕过锁的直连/旧客户端并发：同幂等键 → 重放
    返回；同槽位 → 按测验口径稳定 422；其余数据库故障照常抛出，不得
    except Exception 假装成功。
    """
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key and "idempotency_key" in str(exc.orig):
            replay = _replay_or_none(
                session,
                vocab_session,
                item_index,
                prompt_type,
                answer_raw,
                idempotency_key,
            )
            if replay is not None:
                return replay
        if "uq_vocab_answer_slot" in str(exc.orig) and one_attempt_per_item:
            raise HTTPException(
                status_code=422, detail="测验每题只能作答一次，不能修改答案"
            ) from exc
        raise
    return None


def submit_answer(
    session: Session,
    vocab_session: VocabularySession,
    snapshot_items: list[dict[str, object]],
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
    one_attempt_per_item: bool = False,
    assignment: VocabularyAssignment | None = None,
) -> VocabularyAnswer:
    """判分与落库：幂等键重放返回原作答；练习允许重试（attempt_no 递增）。

    幂等键绑定会话+题号+出题方式+规范化答案：命中其它绑定属于客户端误用，
    按 422 拒绝（避免把别人的旧作答当成当前学生的提交返回）。
    题单由 session_snapshot 统一解析（任务快照或自主轮固化题单）。
    one_attempt_per_item（测验口径）：同题第二次提交 422；断网重传走
    幂等键重放，不受一次性限制误伤。

    并发约定：提交/手动交卷/到时结算共享 VocabularySession 行锁。锁内
    重新校验状态与服务端时间后再写入——服务端以锁内接纳时刻为顺序判定点，
    交卷生效后不再接收新答案；校验与插入之间没有 helper commit 释放锁。
    """
    replay = _replay_or_none(
        session, vocab_session, item_index, prompt_type, answer_raw, idempotency_key
    )
    if replay is not None:
        return replay

    snapshot_item = _validate_answer_input(snapshot_items, item_index, prompt_type)
    normalized = _normalized_answer_or_422(answer_raw)
    is_correct = check_spelling(answer_raw, snapshot_item)

    # 会话行锁（提交/交卷/结算共用）：锁内重校验，封死 check-then-insert 竞态
    session.refresh(vocab_session, with_for_update=True)

    # 锁内重查幂等键：并发同键请求在对方提交后进锁，必须按重放返回而非
    # 被一次性限制/终态门禁拒绝——断网重传的语义以锁内状态为准
    replay = _replay_or_none(
        session, vocab_session, item_index, prompt_type, answer_raw, idempotency_key
    )
    if replay is not None:
        return replay

    _guard_quiz_timing(
        session, vocab_session, assignment, one_attempt_per_item=one_attempt_per_item
    )
    attempt_no = _next_attempt_no(
        session, vocab_session, item_index, one_attempt_per_item=one_attempt_per_item
    )

    answer = _build_answer(
        vocab_session,
        snapshot_item,
        item_index=item_index,
        attempt_no=attempt_no,
        prompt_type=prompt_type,
        answer_raw=answer_raw,
        normalized=normalized,
        is_correct=is_correct,
        idempotency_key=idempotency_key,
    )
    session.add(answer)
    if not one_attempt_per_item:
        _advance_practice_session(session, vocab_session, snapshot_items, item_index)
    replayed = _commit_or_resolve_conflict(
        session,
        vocab_session,
        one_attempt_per_item=one_attempt_per_item,
        item_index=item_index,
        prompt_type=prompt_type,
        answer_raw=answer_raw,
        idempotency_key=idempotency_key,
    )
    if replayed is not None:
        return replayed
    session.refresh(answer)
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


def _load_classroom_rounds(
    session: Session, classroom_id: uuid.UUID, assignment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[VocabularySession]]:
    """按任务分组的轮次（含全部学生）。"""
    rounds_by_assignment: dict[uuid.UUID, list[VocabularySession]] = {}
    for vs in session.exec(
        select(VocabularySession).where(
            VocabularySession.classroom_id == classroom_id,  # type: ignore[arg-type]
            col(VocabularySession.assignment_id).in_(assignment_ids),  # type: ignore[operator]
        )
    ).all():
        if vs.assignment_id is not None:
            rounds_by_assignment.setdefault(vs.assignment_id, []).append(vs)
    return rounds_by_assignment


def _load_targets_by_assignment(
    session: Session, assignment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    targets_by_assignment: dict[uuid.UUID, set[uuid.UUID]] = {}
    for target in session.exec(
        select(VocabularyAssignmentTarget).where(
            col(VocabularyAssignmentTarget.assignment_id).in_(  # type: ignore[operator]
                assignment_ids
            )
        )
    ).all():
        targets_by_assignment.setdefault(target.assignment_id, set()).add(
            target.student_id
        )
    return targets_by_assignment


def _assignment_counters(
    assignment: VocabularyAssignment,
    target_ids: set[uuid.UUID],
    rounds: list[VocabularySession],
    firsts: dict,
) -> tuple[dict[str, int], int]:
    """单个任务的名单进度汇总：（计数, 逾期数）。"""
    total = len(assignment.snapshot_items)
    rounds_by_student: dict[uuid.UUID, list[VocabularySession]] = {}
    for vs in rounds:
        rounds_by_student.setdefault(vs.student_id, []).append(vs)
    counters = {"completed": 0, "in_progress": 0, "not_started": 0}
    overdue_count = 0
    for student_id in target_ids:
        student_rounds = sorted(
            rounds_by_student.get(student_id, []), key=lambda r: r.round_no
        )
        item_firsts = firsts.get(student_rounds[0].id, {}) if student_rounds else {}
        progress = progress_of_round1(total, item_firsts)
        counters[progress] += 1
        if is_overdue(assignment, progress):
            overdue_count += 1
    return counters, overdue_count


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
    assignment_ids = [a.id for a in assignments]
    rounds_by_assignment = _load_classroom_rounds(session, classroom_id, assignment_ids)
    # 进度只消费每生首轮（round_no 最小）的首答：预取按（任务,学生）取首轮，
    # 不再拉全部轮次的首答
    first_round_ids = [
        vs.id
        for rounds in rounds_by_assignment.values()
        for vs in _min_round_by_student(rounds).values()
    ]
    firsts = first_answers_by_session(session, first_round_ids)
    targets_by_assignment = _load_targets_by_assignment(session, assignment_ids)

    rows: list[VocabularyTeacherAssignmentRow] = []
    for assignment in assignments:
        target_ids = targets_by_assignment.get(assignment.id, set())
        counters, overdue_count = _assignment_counters(
            assignment,
            target_ids,
            rounds_by_assignment.get(assignment.id, []),
            firsts,
        )
        rows.append(
            VocabularyTeacherAssignmentRow(
                assignment=assignment_public(assignment),
                target_count=len(target_ids),
                completed_count=counters["completed"],
                in_progress_count=counters["in_progress"],
                not_started_count=counters["not_started"],
                overdue_count=overdue_count,
            )
        )
    return rows


def _result_targets(session: Session, assignment: VocabularyAssignment):
    """按指派名册取（目标，学生），按学生名排序。"""
    return session.exec(
        select(VocabularyAssignmentTarget, Student)
        .join(Student, Student.id == VocabularyAssignmentTarget.student_id)  # ty: ignore[invalid-argument-type]
        .where(VocabularyAssignmentTarget.assignment_id == assignment.id)  # type: ignore[arg-type]
        .order_by(col(Student.display_name))
    ).all()


def _result_rounds(
    session: Session, assignment: VocabularyAssignment, has_targets: bool
) -> tuple[dict[uuid.UUID, list[VocabularySession]], list[VocabularySession]]:
    """按学生聚合会话轮次，并给出扁平列表；无指派时不查库。"""
    rounds_by_student: dict[uuid.UUID, list[VocabularySession]] = {}
    if has_targets:
        for vs in session.exec(
            select(VocabularySession)
            .where(VocabularySession.assignment_id == assignment.id)  # type: ignore[arg-type]
            .order_by(col(VocabularySession.round_no))
        ).all():
            rounds_by_student.setdefault(vs.student_id, []).append(vs)
    all_rounds = [vs for rounds in rounds_by_student.values() for vs in rounds]
    return rounds_by_student, all_rounds


def _retake_flags(targets: list) -> dict[uuid.UUID, bool]:
    return {
        target.student_id: target.retake_granted_at is not None
        for target, _student in targets
    }


def _first_round(rounds: list[VocabularySession]) -> VocabularySession | None:
    # 存量数据迁移后恒有 round_no=1；防御性回落到最早轮
    return rounds[0] if rounds else None


def _student_item_firsts(
    *,
    is_quiz: bool,
    effective: VocabularySession | None,
    quiz_rounds: list[VocabularySession],
    first_round_session: VocabularySession | None,
    firsts: dict,
) -> dict[int, VocabularyAnswer]:
    """取该学生用于统计的首答集合。

    测验：有效成绩存在时用有效答卷，否则用最新进行中答卷（口径统一：答对/
    答错/未答与逐词分布同源，不跨轮逐题择优；尚无终结答卷时只作进度）；
    练习：锁定首轮首答，复习轮只进 rounds 汇总。
    """
    if is_quiz:
        progress_round = (
            effective
            if effective is not None
            else quiz_rounds[-1]
            if quiz_rounds
            else None
        )
        if progress_round is None:
            return {}
        return dict(firsts.get(progress_round.id, {}) or {})
    if first_round_session is None:
        return {}
    return dict(firsts.get(first_round_session.id, {}) or {})


def _student_status(
    *, is_quiz: bool, answered: int, total: int, rounds: list[VocabularySession]
) -> str:
    if is_quiz:
        # 测验状态以答卷终结方式判定：全部答卷已终结 = completed
        latest = rounds[-1] if rounds else None
        if not rounds or all(r.quiz_started_at is None for r in rounds):
            return "not_started"
        if latest is not None and latest.status == "in_progress":
            return "in_progress"
        return "completed"
    if answered == 0 and not rounds:
        return "not_started"
    if answered >= total:
        return "completed"
    return "in_progress"


def _student_round_rows(
    rounds: list[VocabularySession], firsts: dict
) -> list[VocabularyStudentRoundRow]:
    return [
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


def _quiz_rounds(rounds: list[VocabularySession]) -> list[VocabularySession]:
    """只保留真正开过考的轮次（练习轮没有 quiz_started_at）。"""
    return [r for r in rounds if r.quiz_started_at is not None]


def _effective_grade(
    assignment: VocabularyAssignment,
    quiz_rounds: list[VocabularySession],
    firsts: dict,
    total: int,
) -> tuple[int | None, bool | None, VocabularySession | None]:
    """有效成绩 = 最好整份已终结答卷（同分取较早轮）；没有终结答卷则全为 None。

    纯聚合复用已批量读取的 rounds/firsts，不逐学生查库。
    """
    finalized = [r for r in quiz_rounds if r.status == "submitted"]
    if not finalized:
        return None, None, None
    best_score, passed, _attempts, effective = (
        vocab_quiz.effective_quiz_grade_from_rounds(
            finalized, firsts, total, assignment.pass_line
        )
    )
    return best_score, passed, effective


def _student_result_row(
    student: Student,
    *,
    rounds: list[VocabularySession],
    total: int,
    firsts: dict,
    item_firsts: dict[int, VocabularyAnswer],
    is_quiz: bool,
    quiz_rounds: list[VocabularySession],
    best_score: int | None,
    passed: bool | None,
    effective: VocabularySession | None,
    retake_granted: bool,
) -> VocabularyStudentResultRow:
    answered = len(item_firsts)
    first_round_session = _first_round(rounds)
    return VocabularyStudentResultRow(
        student_id=student.id,
        display_name=student.display_name,
        suffix=student.suffix,
        status=_student_status(
            is_quiz=is_quiz, answered=answered, total=total, rounds=rounds
        ),
        answered_count=answered,
        correct_first_count=sum(1 for a in item_firsts.values() if a.is_correct),
        total_count=total,
        submitted_at=(
            first_round_session.submitted_at if first_round_session else None
        ),
        round_count=len(rounds),
        rounds=_student_round_rows(rounds, firsts),
        quiz_end_reason=(quiz_rounds[-1].end_reason if quiz_rounds else None),
        score=best_score if is_quiz else None,
        passed=passed if is_quiz else None,
        effective_round_no=(effective.round_no if effective else None),
        tab_switch_count=(
            sum(vs.tab_switch_count for vs in quiz_rounds) if is_quiz else 0
        ),
        retake_granted=retake_granted,
        attempt_count=len(quiz_rounds),
    )


def _word_stat_rows(
    assignment: VocabularyAssignment, word_firsts: dict[int, list[VocabularyAnswer]]
) -> list[VocabularyWordStatRow]:
    rows: list[VocabularyWordStatRow] = []
    for idx, snapshot_item in enumerate(assignment.snapshot_items):
        answers = word_firsts.get(idx, [])
        correct = sum(1 for a in answers if a.is_correct)
        wrong = [a for a in answers if not a.is_correct]
        misspelling_counter = Counter(a.answer_normalized for a in wrong)
        misspellings = [
            VocabularyWordMisspelling(answer=answer, count=count)
            for answer, count in misspelling_counter.most_common(5)
        ]
        rows.append(
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
    return rows


def class_results(
    session: Session, assignment: VocabularyAssignment
) -> tuple[list, list]:
    """按目标名单聚合：学生行（含未开始）+ 逐词错误分布。

    练习：任务成绩锁定 round_no=1 的首答；复习轮只进 rounds 汇总。
    测验：先到时结算（不依赖学生在线）；有效成绩 = 最好整份已终结答卷
    （同分取较早轮，effective_round_no 标注来源），答对/答错/未答与逐词
    错误分布与成绩同源（不跨轮逐题择优）；进行中补考只作进度。
    全部数据复用批量读取的 rounds/firsts（纯聚合），查询数不随学生数增长。
    """
    is_quiz = assignment.mode == "quiz"
    if is_quiz:
        # 教师侧触碰即完成到时结算（结果不依赖学生页面在线）
        vocab_quiz.settle_due_sessions(session, assignment)

    targets = _result_targets(session, assignment)
    rounds_by_student, all_rounds = _result_rounds(session, assignment, bool(targets))
    firsts = first_answers_by_session(session, [vs.id for vs in all_rounds])
    retake_by_student = _retake_flags(targets)

    student_rows: list[VocabularyStudentResultRow] = []
    word_firsts: dict[int, list[VocabularyAnswer]] = {}
    for _target, student in targets:
        rounds = rounds_by_student.get(student.id, [])
        total = len(assignment.snapshot_items)
        quiz_rounds = _quiz_rounds(rounds) if is_quiz else []
        best_score, passed, effective = _effective_grade(
            assignment, quiz_rounds, firsts, total
        )
        item_firsts = _student_item_firsts(
            is_quiz=is_quiz,
            effective=effective,
            quiz_rounds=quiz_rounds,
            first_round_session=_first_round(rounds),
            firsts=firsts,
        )
        for idx, answer in item_firsts.items():
            word_firsts.setdefault(idx, []).append(answer)
        student_rows.append(
            _student_result_row(
                student,
                rounds=rounds,
                total=total,
                firsts=firsts,
                item_firsts=item_firsts,
                is_quiz=is_quiz,
                quiz_rounds=quiz_rounds,
                best_score=best_score,
                passed=passed,
                effective=effective,
                retake_granted=retake_by_student.get(student.id, False),
            )
        )

    return student_rows, _word_stat_rows(assignment, word_firsts)


def _wrong_word_answers(
    session: Session, student_id: uuid.UUID
) -> list[VocabularyAnswer]:
    """该学生全部可按错词本的作答证据（按作答时间 + 尝试序升序）。

    答案可见规则：测验答卷在答案公布前不进错词本（提前收录等于泄露对错）。
    """
    return list(
        session.exec(
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
                (col(VocabularySession.assignment_id).is_(None))  # type: ignore[union-attr]
                | (col(VocabularyAssignment.mode) != "quiz")  # type: ignore[operator]
                | col(VocabularyAssignment.answers_published_at).is_not(None),  # type: ignore[union-attr]
            )
            .order_by(
                col(VocabularyAnswer.answered_at), col(VocabularyAnswer.attempt_no)
            )
        ).all()
    )


def _aggregate_wrong_words(
    answers: list[VocabularyAnswer],
) -> tuple[dict[uuid.UUID, VocabularyWrongWordItem], dict[uuid.UUID, datetime]]:
    """聚合出进本词条 + 每个词的最近答对时间。

    - wrong_count 只统计独立首答（attempt_no=1）判错次数，只增不减
    - last_first_* 是最近一次独立首答的时间与对错
    - last_correct_at 是最近一次答对时间（任意尝试，含首次判错之前）
    """
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
    return by_word, last_correct_at


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
    answers = _wrong_word_answers(session, student_id)
    by_word, last_correct_at = _aggregate_wrong_words(answers)
    items = sorted(by_word.values(), key=lambda i: (-i.wrong_count, i.headword))
    for item in items:
        item.last_correct_at = last_correct_at.get(item.word_id)
    if practiceable_ids is not None:
        for item in items:
            item.practiceable = item.word_id in practiceable_ids
    return items


def wrong_word_count(session: Session, student_id: uuid.UUID) -> int:
    """错词本词数（与 wrong_word_items 同口径的计数版）。

    今日视图高频调用只需要 len()，这里用 SQL 聚合避免拉全量作答历史
    与整行 ORM 对象。口径：至少一次独立首答（attempt_no=1）判错的
    去重词条数，测验答卷在答案公布前不计入（与 wrong_word_items 一致）。
    """
    return int(
        session.exec(
            select(func.count(func.distinct(VocabularyAnswer.word_id)))
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
                VocabularyAnswer.attempt_no == 1,
                col(VocabularyAnswer.is_correct).is_(False),
                (col(VocabularySession.assignment_id).is_(None))  # type: ignore[union-attr]
                | (col(VocabularyAssignment.mode) != "quiz")  # type: ignore[operator]
                | col(VocabularyAssignment.answers_published_at).is_not(None),  # type: ignore[union-attr]
            )
        ).one()
    )


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


def _resume_session_conditions(
    student_id: uuid.UUID, kind: str, book_id: uuid.UUID | None
) -> list:
    """续做幂等的查询条件：同学生同类型（self 另要求同词库）的进行中轮。"""
    conditions: list = [
        VocabularySession.student_id == student_id,  # type: ignore[arg-type]
        VocabularySession.kind == kind,  # type: ignore[arg-type]
        VocabularySession.status == "in_progress",  # type: ignore[arg-type]
    ]
    if kind == "self":
        conditions.append(VocabularySession.source_book_id == book_id)  # type: ignore[arg-type]
    return conditions


def _commit_or_find_winner(
    session: Session,
    vocab_session: VocabularySession,
    resume_conditions: list,
) -> VocabularySession:
    """提交新轮次；撞部分唯一索引时回滚并返回并发赢家轮次。

    uq_vocab_session_self_active / uq_vocab_session_review_active 保证并发
    开轮也只产生一个进行中轮次。
    """
    try:
        session.commit()
        return vocab_session
    except Exception:
        session.rollback()
        winner = session.exec(
            select(VocabularySession).where(*resume_conditions)
        ).first()
        if winner is None:
            raise
        return winner


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
    resume_conditions = _resume_session_conditions(student_id, kind, book_id)
    resume = session.exec(select(VocabularySession).where(*resume_conditions)).first()
    if resume is not None:
        return (
            resume,
            _student_session_title(session, resume),
            _snapshot_wrong_count(resume),
        )

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
    committed = _commit_or_find_winner(session, vocab_session, resume_conditions)
    if committed is not vocab_session:
        # 并发输家：返回赢家轮次
        return (
            committed,
            _student_session_title(session, committed),
            _snapshot_wrong_count(committed),
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


def _self_book_words(
    session: Session, classroom_id: uuid.UUID, book_id: uuid.UUID | None
) -> tuple[VocabularyBook, list[VocabularyWord]]:
    """校验词库可用性与归属，返回（词库, 可用词）。"""
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
    return book, words


def _pick_wrong_words(
    session: Session,
    student_id: uuid.UUID,
    words: list[VocabularyWord],
    total: int,
    mix_wrong: bool,
) -> tuple[list[VocabularyWord], set[uuid.UUID]]:
    """混错词：只取所选词库内的历史错词，最近错误优先，按词条 ID 去重。"""
    if not mix_wrong:
        return [], set()
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
    return [w for w in words if w.id in wanted], wrong_pool_ids


def _fill_remaining_words(
    words: list[VocabularyWord],
    picked_ids: set[uuid.UUID],
    wrong_pool_ids: set[uuid.UUID],
    remaining: int,
) -> tuple[list[VocabularyWord], list[VocabularyWord]]:
    """补位：优先非错词；非错词不足时才用其余错词补足（同样计入错词标记）。

    优先非错词保证普通词充足时混入占比恒 ≤ 目标。
    """
    plain_fill = [
        w for w in words if w.id not in picked_ids and w.id not in wrong_pool_ids
    ][:remaining]
    extra_wrong: list[VocabularyWord] = []
    if len(plain_fill) < remaining:
        extra_wrong = [
            w for w in words if w.id not in picked_ids and w.id in wrong_pool_ids
        ][: remaining - len(plain_fill)]
    return plain_fill, extra_wrong


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
    book, words = _self_book_words(session, classroom_id, book_id)
    total = min(word_count, len(words))
    picked_wrong, wrong_pool_ids = _pick_wrong_words(
        session, student_id, words, total, mix_wrong
    )

    picked_ids = {w.id for w in picked_wrong}
    plain_fill, extra_wrong = _fill_remaining_words(
        words, picked_ids, wrong_pool_ids, total - len(picked_wrong)
    )
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


def _plan_context(
    session: Session, vocab_session: VocabularySession
) -> tuple[VocabularyAssignment | None, bool, list[dict[str, object]]]:
    """取任务、是否测验、题单；测验先到时结算（不依赖学生页面在线）。"""
    assignment = (
        session.get(VocabularyAssignment, vocab_session.assignment_id)
        if vocab_session.assignment_id is not None
        else None
    )
    is_quiz = assignment is not None and assignment.mode == "quiz"
    if is_quiz and assignment is not None:
        vocab_quiz.settle_due_sessions(session, assignment)
        session.refresh(vocab_session)
    snapshot_items = session_snapshot(session, vocab_session)
    return assignment, is_quiz, snapshot_items


def _visibility_flags(
    reveal: bool, is_quiz: bool, assignment: VocabularyAssignment | None
) -> tuple[bool, bool]:
    """（答案可见, 成绩可见）。reveal=True（教师查看）不受公布规则约束。"""
    answers_visible = reveal or not (
        is_quiz and assignment is not None and assignment.answers_published_at is None
    )
    score_visible = reveal or not (
        is_quiz and assignment is not None and assignment.grades_published_at is None
    )
    return answers_visible, score_visible


def _plan_item(
    idx: int,
    snapshot_item: dict[str, object],
    attempts: list[VocabularyAnswer],
    *,
    answers_visible: bool,
) -> tuple[VocabularyStudentItem, bool, bool]:
    """单题视图 +（是否已答, 首答是否正确）计数增量。

    未作答不透露拼写；测验答案未公布时已答也不揭示正确拼写与对错。
    """
    first = next((a for a in attempts if a.attempt_no == 1), None)
    item_prompt_types = snapshot_item.get("prompt_types")
    audio_allowed = (
        isinstance(item_prompt_types, list)
        and "audio" in item_prompt_types
        and (snapshot_item.get("audio_url") is not None or first is not None)
    )
    item = VocabularyStudentItem(
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
    answered = first is not None
    correct = answered and first.is_correct
    return item, answered, correct


def _plan_countdown(
    vocab_session: VocabularySession,
    assignment: VocabularyAssignment | None,
    *,
    is_quiz: bool,
) -> tuple[datetime | None, int | None]:
    """测验截止时刻与剩余秒数；进行中才给剩余时间。"""
    if not (is_quiz and assignment is not None):
        return None, None
    deadline = vocab_quiz.quiz_deadline(vocab_session, assignment)
    remaining = None
    if vocab_session.status == "in_progress" and deadline is not None:
        remaining = max(0, int((deadline - datetime.now(UTC)).total_seconds()))
    return deadline, remaining


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
    assignment, is_quiz, snapshot_items = _plan_context(session, vocab_session)
    answers_visible, score_visible = _visibility_flags(reveal, is_quiz, assignment)
    grouped = answers_by_item(session, vocab_session.id)

    items: list[VocabularyStudentItem] = []
    answered_count = 0
    correct_first = 0
    for idx, snapshot_item in enumerate(snapshot_items):
        item, answered, correct = _plan_item(
            idx,
            snapshot_item,
            grouped.get(idx, []),
            answers_visible=answers_visible,
        )
        items.append(item)
        if answered:
            answered_count += 1
            if correct:
                correct_first += 1

    title = _student_session_title(session, vocab_session)
    deadline, remaining = _plan_countdown(vocab_session, assignment, is_quiz=is_quiz)
    masked = is_quiz and not score_visible
    return VocabularyStudentPlan(
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


def _load_history_rounds(
    session: Session, student_id: uuid.UUID, limit: int
) -> list[VocabularySession]:
    """最近若干轮次（按开始时间倒序，limit 已夹取）。"""
    return list(
        session.exec(
            select(VocabularySession)
            .where(VocabularySession.student_id == student_id)  # type: ignore[arg-type]
            .order_by(col(VocabularySession.started_at).desc())
            .limit(limit)
        ).all()
    )


def _load_assignments_by_id(
    session: Session, assignment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VocabularyAssignment]:
    if not assignment_ids:
        return {}
    return {
        a.id: a
        for a in session.exec(
            select(VocabularyAssignment).where(
                col(VocabularyAssignment.id).in_(assignment_ids)  # type: ignore[operator]
            )
        ).all()
    }


def _history_row(
    session: Session,
    vocab_session: VocabularySession,
    item_firsts: dict[int, VocabularyAnswer],
    assignments: dict[uuid.UUID, VocabularyAssignment],
) -> VocabularyStudentHistoryRow:
    """单轮历史行：标题/题量按任务或自主轮取值，测验遵守公布规则。"""
    assignment = (
        assignments.get(vocab_session.assignment_id)
        if vocab_session.assignment_id
        else None
    )
    if vocab_session.assignment_id is not None:
        title = assignment.title if assignment else "词汇任务"
        total = len(assignment.snapshot_items) if assignment else 0
    else:
        title = _student_session_title(session, vocab_session)
        total = len(vocab_session.snapshot_items or [])
    is_quiz = assignment is not None and assignment.mode == "quiz"
    # 测验结算不依赖学生在线：触碰历史时把到时答卷收口
    if is_quiz and vocab_session.status == "in_progress" and assignment is not None:
        vocab_quiz.settle_due_sessions(session, assignment)
        session.refresh(vocab_session)
    # 答案可见规则：测验成绩未公布 → 只下发提交状态（correct 置 0 +
    # masked 标记，前端隐藏成绩维度，不显示"首答 0"）
    masked = (
        is_quiz and assignment is not None and (assignment.grades_published_at is None)
    )
    return VocabularyStudentHistoryRow(
        session_id=vocab_session.id,
        kind=vocab_session.kind,
        title=title,
        status=vocab_session.status,
        round_no=(
            vocab_session.round_no if vocab_session.assignment_id is not None else None
        ),
        total_count=total,
        answered_count=len(item_firsts),
        correct_first_count=0
        if masked
        else sum(1 for a in item_firsts.values() if a.is_correct),
        started_at=vocab_session.started_at,
        submitted_at=vocab_session.submitted_at,
        book_id=vocab_session.source_book_id,
        assignment_id=vocab_session.assignment_id,
        masked=masked,
        is_quiz=is_quiz,
        end_reason=vocab_session.end_reason,
    )


def history_rows(
    session: Session, student_id: uuid.UUID, limit: int = 50
) -> list[VocabularyStudentHistoryRow]:
    """练习历史（含任务轮/自主轮/复习轮），按开始时间倒序。

    正确率不在行内预计算：口径是 correct_first_count / answered_count
    （首答正确率分母为已答题数），零作答显示未作答，不画成 0%。
    """
    rounds = _load_history_rounds(session, student_id, max(1, min(limit, 200)))
    assignment_ids = [r.assignment_id for r in rounds if r.assignment_id is not None]
    assignments = _load_assignments_by_id(session, assignment_ids)
    firsts = first_answers_by_session(session, [r.id for r in rounds])
    return [_history_row(session, r, firsts.get(r.id, {}), assignments) for r in rounds]


# ── 词库加词域（routes/vocabulary 与 services/vocab_ai 共用）──────────
# 原路由层 helper 下沉：vocab_ai 曾反向 import 路由层（服务依赖路由的
# 倒挂），加词/计数/取库/编辑权全部收敛在此。

MAX_BOOK_WORDS = 500


def get_book_or_404(session: Session, book_id: uuid.UUID) -> VocabularyBook:
    book = session.get(VocabularyBook, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="词库不存在")
    return book


def require_book_editor(book: VocabularyBook, current_user: User) -> None:
    """词库编辑权：公共词库仅管理员；班级词库为本班教师或管理员。

    多租户：管理员放行只在本校成立——跨校词库按不存在处理
    （CLAUDE.md 不变量④，与 RLS 激活环境对齐）。
    """
    if book.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="词库不存在")
    if current_user.role == "school_admin":
        return
    if (
        book.scope == "classroom"
        and book.classroom_id is not None
        and book.owner_id == current_user.id
    ):
        return
    raise HTTPException(status_code=403, detail="没有权限编辑这个词库")


def word_count_by_book(
    session: Session, book_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not book_ids:
        return {}
    rows = session.exec(
        select(VocabularyBookItem.book_id, func.count())
        .where(col(VocabularyBookItem.book_id).in_(book_ids))  # type: ignore[operator]
        .group_by(VocabularyBookItem.book_id)  # ty: ignore[invalid-argument-type]
    ).all()
    return dict(rows)


def _create_word(session: Session, word_in: VocabularyWordIn) -> VocabularyWord:
    word = VocabularyWord(
        headword=word_in.headword.strip(),
        part_of_speech=(word_in.part_of_speech or "").strip() or None,
        meaning_zh=word_in.meaning_zh.strip(),
        meaning_en=(word_in.meaning_en or "").strip() or None,
        accepted_spellings=[
            spelling.strip()
            for spelling in (word_in.accepted_spellings or [])
            if spelling.strip()
        ]
        or None,
        example_en=(word_in.example_en or "").strip() or None,
        audio_url=(word_in.audio_url or "").strip() or None,
    )
    session.add(word)
    return word


def _next_position(session: Session, book_id: uuid.UUID) -> int:
    latest = session.exec(
        select(VocabularyBookItem.position)
        .where(VocabularyBookItem.book_id == book_id)
        .order_by(col(VocabularyBookItem.position).desc())
    ).first()
    return (latest or 0) + 1


def _known_book_word_keys(
    session: Session, book: VocabularyBook
) -> tuple[set[tuple[str, str]], int]:
    """已有（headword casefold, 释义）键集合 + 下一个可用 position。"""
    existing_items = session.exec(
        select(VocabularyBookItem.word_id).where(
            VocabularyBookItem.book_id == book.id  # type: ignore[arg-type]
        )
    ).all()
    existing_words = {
        w.id: w
        for w in session.exec(
            select(VocabularyWord).where(
                col(VocabularyWord.id).in_(existing_items or [uuid.uuid4()])
            )  # type: ignore[operator]
        ).all()
    }
    known = {(w.headword.casefold(), w.meaning_zh) for w in existing_words.values()}
    return known, _next_position(session, book.id)


def _collect_new_words(
    session: Session, words_in: list[VocabularyWordIn], known: set[tuple[str, str]]
) -> list[VocabularyWord]:
    """同库已收的词跳过（键为 headword+释义）；返回需要落库的新词。"""
    new_words: list[VocabularyWord] = []
    for word_in in words_in:
        key = (word_in.headword.strip().casefold(), word_in.meaning_zh.strip())
        if key in known:
            continue
        known.add(key)
        new_words.append(_create_word(session, word_in))
    return new_words


def _attach_words_to_book(
    session: Session,
    book: VocabularyBook,
    new_words: list[VocabularyWord],
    position: int,
) -> None:
    """先 flush 词条再挂词库条目，并在锁内自增 version。

    词与词库条目之间没有 relationship，unit-of-work 不保证跨 mapper 的
    INSERT 顺序——必须先 flush 完全部词条再挂条目。
    """
    session.flush()
    for word in new_words:
        session.add(
            VocabularyBookItem(book_id=book.id, word_id=word.id, position=position)
        )
        position += 1
    session.execute(  # ty: ignore[deprecated] - exec() 不接受 update 语句
        update(VocabularyBook)
        .where(col(VocabularyBook.id) == book.id)
        .values(version=VocabularyBook.version + 1)
    )


def add_words_to_book(
    session: Session, book: VocabularyBook, words_in: list[VocabularyWordIn]
) -> int:
    """词库内加词；同库已收的词（headword+释义一致）跳过。返回新增数。

    并发竞态：两个请求同时从 max(position)+1 起编号会拿到相同 position
    （词序错乱/教师预览与学生测验不一致）。锁词库行串行化同库并发编辑，
    version 自增也在锁内——与读侧快照天然一致。
    """
    if not words_in:
        return 0
    if len(words_in) > MAX_BOOK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"单次最多加入 {MAX_BOOK_WORDS} 个词"
        )
    locked_book = session.exec(
        select(VocabularyBook).where(VocabularyBook.id == book.id).with_for_update()
    ).first()
    if locked_book is None:
        raise HTTPException(status_code=404, detail="词库不存在")
    known, position = _known_book_word_keys(session, book)
    new_words = _collect_new_words(session, words_in, known)
    if new_words:
        _attach_words_to_book(session, book, new_words, position)
    session.commit()
    return len(new_words)
