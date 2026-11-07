"""词汇学习（背单词）模块接口。

    /vocabulary/books                 词库 CRUD + 词库内加词（教师/管理员）
    /vocabulary/books/import-preview  CSV 解析预览（不落库）
    /vocabulary/words/{id}            词条编辑
    /classes/{code}/vocabulary/...    课堂发布 / 学生任务 / 结果 / 错词本
    /vocabulary/sessions/{id}/answers 学生作答（服务端判分）

权限口径（设计文档 §5）：词库编辑/发布 = 课堂所有者教师或管理员；
学生任务仅目标名单内的本班学生；原始作答仅本人与该班教师可读。
401 只表示登录失效；权限不足一律 403。
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.api.routes.classes import (
    _get_classroom,
    _require_classroom_teacher,
)
from app.models import (
    User,
    VocabularyAssignment,
    VocabularyAssignmentPublic,
    VocabularyBook,
    VocabularyBookPublic,
    VocabularyClassResults,
    VocabularyQuizState,
    VocabularyRoundSummaryRow,
    VocabularySession,
    VocabularyTodayItem,
    VocabularyTodayPlan,
    VocabularyWord,
    VocabularyWordPublic,
)
from app.services import vocab_quiz
from app.services import vocabulary as vocab_service
from app.services.csv_safety import csv_safe

logger = logging.getLogger(__name__)
# ── 权限与组装辅助 ──────────────────────────────────────────────────


def _word_public(word: VocabularyWord) -> VocabularyWordPublic:
    return VocabularyWordPublic(
        id=word.id,
        headword=word.headword,
        part_of_speech=word.part_of_speech,
        meaning_zh=word.meaning_zh,
        meaning_en=word.meaning_en,
        accepted_spellings=word.accepted_spellings,
        example_en=word.example_en,
        audio_url=word.audio_url,
        status=word.status,
    )


def _book_public(book: VocabularyBook, word_count: int) -> VocabularyBookPublic:
    return VocabularyBookPublic(
        id=book.id,
        title=book.title,
        description=book.description,
        scope=book.scope,
        classroom_id=book.classroom_id,
        owner_id=book.owner_id,
        status=book.status,
        word_count=word_count,
        created_at=book.created_at,
    )


def _assignment_public(assignment: VocabularyAssignment) -> VocabularyAssignmentPublic:
    return vocab_service.assignment_public(assignment)


def _book_visible(book: VocabularyBook, current_user: User) -> bool:
    # 多租户：先按本校过滤（他校词库在 RLS 激活环境本就查不到；
    # 无 RLS 环境保持同语义，CLAUDE.md 不变量④）
    if book.tenant_id != current_user.tenant_id:
        return False
    if current_user.role == "school_admin":
        return True
    if book.scope == "public":
        return True
    return book.owner_id == current_user.id


# ── 课堂发布（教师） ────────────────────────────────────────────────


def _get_assignment(
    session: Session, classroom_id: uuid.UUID, assignment_id: uuid.UUID
) -> VocabularyAssignment:
    assignment = session.get(VocabularyAssignment, assignment_id)
    if assignment is None or assignment.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="词汇任务不存在")
    return assignment


# ── 学生端 ─────────────────────────────────────────────────────────


def _student_rounds(
    session: Session, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> list[VocabularySession]:
    """该学生在此任务的全部轮次（round_no 升序；归属由 student_id 过滤）。"""
    return list(
        session.exec(
            select(VocabularySession)
            .where(
                VocabularySession.assignment_id == assignment_id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            )
            .order_by(col(VocabularySession.round_no))
        ).all()
    )


def _focused_vocab_session(
    session: Session,
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    round_no: int | None = None,
    rounds: list[VocabularySession] | None = None,
) -> VocabularySession | None:
    """展示轮次：显式 round_no 回看指定轮；缺省未结束轮优先，否则最新轮。

    rounds 传入调用方已查的轮次清单可省一次同参查询（today 路径原本
    同参查 3 次：列表 + 展示轮 + 可练轮）。
    """
    if rounds is None:
        rounds = _student_rounds(session, assignment_id, student_id)
    if round_no is not None:
        return next((r for r in rounds if r.round_no == round_no), None)
    unfinished = next((r for r in rounds if r.status == "in_progress"), None)
    return unfinished if unfinished is not None else (rounds[-1] if rounds else None)


def _session_closed_reason(assignment: VocabularyAssignment) -> str | None:
    """任务级作答门禁原因（独立于会话状态）：not_open / due_passed / archived。

    已完成会话同样计算——「是否还能开练/作答」只取决于任务本身。
    """
    if assignment.status != "published":
        return "archived"
    now = datetime.now(UTC)
    if assignment.opens_at is not None and now < assignment.opens_at:
        return "not_open"
    if assignment.due_at is not None and now >= assignment.due_at:
        return "due_passed"
    return None


def _round_summary_rows(
    session: Session, rounds: list[VocabularySession], masked: bool = False
) -> list[VocabularyRoundSummaryRow]:
    """各轮首答摘要（口径与教师统计一致：attempt_no=1）。

    测验成绩未公布时 masked=True：correct_first_count 置 0 不下发，
    前端只展示轮次与状态，不显示对错数。
    """
    if not rounds:
        return []
    firsts = vocab_service.first_answers_by_session(session, [vs.id for vs in rounds])
    return [
        VocabularyRoundSummaryRow(
            round_no=vs.round_no,
            status=vs.status,
            answered_count=len(firsts.get(vs.id, {})),
            correct_first_count=(
                0
                if masked
                else sum(1 for a in firsts.get(vs.id, {}).values() if a.is_correct)
            ),
            submitted_at=vs.submitted_at,
            masked=masked,
            end_reason=vs.end_reason,
        )
        for vs in rounds
    ]


def _quiz_state(
    session: Session,
    assignment: VocabularyAssignment,
    student_id: uuid.UUID,
    rounds: list[VocabularySession],
) -> VocabularyQuizState:
    """学生侧测验状态（规则 + 个人计时 + 参与/公布进度）。"""
    from app.services import vocab_quiz

    quiz_rounds = [r for r in rounds if r.quiz_started_at is not None]
    latest = quiz_rounds[-1] if quiz_rounds else None
    if latest is None:
        status = "not_started"
    elif latest.status == "in_progress":
        status = "in_progress"
    else:
        status = "timed_out" if latest.end_reason == "timeout" else "submitted"
    started_at = latest.quiz_started_at if latest else None
    deadline = (
        vocab_quiz.quiz_deadline(latest, assignment) if latest is not None else None
    )
    remaining = None
    if status == "in_progress" and deadline is not None:
        remaining = max(0, int((deadline - datetime.now(UTC)).total_seconds()))
    score_visible = assignment.grades_published_at is not None
    score: int | None = None
    passed: bool | None = None
    if score_visible and quiz_rounds:
        score, passed, _attempts = vocab_quiz.effective_quiz_grade(
            session, assignment, student_id
        )
    return VocabularyQuizState(
        status=status,
        attempts_used=len(quiz_rounds),
        attempts_allowed=vocab_quiz.attempts_allowed(
            session, assignment.id, student_id
        ),
        retake_granted=vocab_quiz.retake_granted(session, assignment.id, student_id),
        duration_minutes=assignment.duration_minutes,
        pass_line=assignment.pass_line,
        opens_at=assignment.opens_at,
        due_at=assignment.due_at,
        started_at=started_at,
        deadline=deadline,
        remaining_seconds=remaining,
        submitted_at=latest.submitted_at if latest else None,
        end_reason=latest.end_reason if latest else None,
        score_visible=score_visible,
        answers_visible=assignment.answers_published_at is not None,
        score=score,
        passed=passed,
        tab_switch_count=latest.tab_switch_count if latest else 0,
    )


def _today_plan_payload(
    session: Session,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    assignment_id: uuid.UUID | None = None,
    round_no: int | None = None,
) -> VocabularyTodayPlan:
    assignments = vocab_service.student_assignment_rows(
        session, classroom_id, student_id
    )
    if assignment_id is not None:
        # 显式指定任务：不存在/非本班/不在名单一律 404，不静默回落
        assignment = session.get(VocabularyAssignment, assignment_id)
        if (
            assignment is None
            or assignment.classroom_id != classroom_id
            or not vocab_service.student_targeted(session, assignment, student_id)
        ):
            raise HTTPException(status_code=404, detail="词汇任务不存在")
    else:
        assignment = vocab_service.focused_assignment(session, classroom_id, student_id)
        if assignment is None or not vocab_service.student_targeted(
            session, assignment, student_id
        ):
            return VocabularyTodayPlan(
                assignments=assignments,
                wrong_word_count=vocab_service.wrong_word_count(session, student_id),
            )

    is_quiz = assignment.mode == "quiz"
    if is_quiz:
        # 到时结算不依赖学生页面在线：触碰任务视图即收口到时答卷
        vocab_quiz.settle_due_sessions(session, assignment)

    # 轮次清单一次查询复用：展示轮与可练轮都从同一份 rounds 挑选
    # （原实现同参查 3 次：清单 + 展示轮 + 可练轮）
    rounds = _student_rounds(session, assignment.id, student_id)
    vocab_session = _focused_vocab_session(
        session, assignment.id, student_id, round_no=round_no, rounds=rounds
    )
    if round_no is not None and vocab_session is None:
        # 显式回看不存在的轮次（含他学生的轮次）：404，不回落
        raise HTTPException(status_code=404, detail="轮次不存在")
    # 当前可练轮独立于展示轮计算：未结束轮优先，否则最新轮
    practice_session = _focused_vocab_session(
        session, assignment.id, student_id, rounds=rounds
    )
    current_round = practice_session.round_no if practice_session is not None else None
    # 答案可见规则：测验在答案公布前，已答题也不揭示拼写与对错
    answers_visible = not (is_quiz and assignment.answers_published_at is None)
    # 测验未开始（无答卷）只下发规则，不下发题面内容
    quiz_rounds = (
        [r for r in rounds if r.quiz_started_at is not None] if is_quiz else rounds
    )
    grouped = (
        vocab_service.answers_by_item(session, vocab_session.id)
        if vocab_session is not None and (not is_quiz or quiz_rounds)
        else {}
    )
    items: list[VocabularyTodayItem] = []
    answered_count = 0
    correct_first = 0
    for idx, snapshot_item in enumerate(assignment.snapshot_items):
        attempts = grouped.get(idx, [])
        first = next((a for a in attempts if a.attempt_no == 1), None)
        if first is not None:
            answered_count += 1
            if first.is_correct:
                correct_first += 1
        # 听音口径（设计文档 §5）：任务含 audio 且该词有稳定标准音；
        # 已作答的词拼写已揭示，可退回设备朗读练耳。其余一律看义拼词，
        # 避免播音按钮无内容可放。
        # 测验更严：设备合成语音不作题源——听音仅限有标准音的词
        # （无论是否已答，避免借设备朗读泄露未公布答案）。
        if is_quiz:
            audio_allowed = "audio" in (assignment.prompt_types or []) and (
                snapshot_item.get("audio_url") is not None
            )
        else:
            audio_allowed = "audio" in (assignment.prompt_types or []) and (
                snapshot_item.get("audio_url") is not None or first is not None
            )
        prompt_type = "audio" if audio_allowed else "meaning"
        items.append(
            VocabularyTodayItem(
                item_index=idx,
                prompt_type=prompt_type,
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
                # 未作答不透露拼写（防看 API 直接抄）；测验答案未公布时
                # 已答题同样不揭示拼写与对错
                headword=(first.headword if first is not None else None)
                if answers_visible
                else None,
                answered=first is not None,
                is_correct=(first.is_correct if first is not None else None)
                if answers_visible
                else None,
                attempt_count=len(attempts),
            )
        )
    if is_quiz and not quiz_rounds:
        # 规则页：未开始不下发题面
        items = []
        answered_count = 0
        correct_first = 0
    grades_masked = is_quiz and assignment.grades_published_at is None
    return VocabularyTodayPlan(
        assignment=_assignment_public(assignment),
        session_id=vocab_session.id if vocab_session is not None else None,
        session_status=vocab_session.status if vocab_session is not None else None,
        session_round=vocab_session.round_no if vocab_session is not None else None,
        current_round=current_round,
        session_closed_reason=_session_closed_reason(assignment),
        items=items,
        # 展示轮的进度（回看历史轮时是该轮的记录）；任务整体进度看 assignments（首轮口径）
        answered_count=answered_count,
        correct_first_count=0 if grades_masked else correct_first,
        quiz=(
            _quiz_state(session, assignment, student_id, rounds) if is_quiz else None
        ),
        rounds=_round_summary_rows(session, rounds, masked=grades_masked),
        assignments=assignments,
        wrong_word_count=vocab_service.wrong_word_count(session, student_id),
    )


def _get_quiz_assignment(
    session: Session, classroom_id: uuid.UUID, assignment_id: uuid.UUID
) -> VocabularyAssignment:
    assignment = _get_assignment(session, classroom_id, assignment_id)
    if assignment.mode != "quiz":
        raise HTTPException(status_code=422, detail="该任务不是测验")
    return assignment


def _csv_text_cell(value: object) -> object:
    """CSV 公式注入防护：实现收敛到 services/csv_safety.py，与前端 csv.ts 同规则。

    Excel/WPS 会把 = + - @ / 制表 / 回车 开头当公式执行（姓名来自导入与
    用户输入）；前缀单引号是最保守的通用转义，数字类型原样保留。
    """
    return csv_safe(value)


def read_vocab_results_payload(
    session: SessionDep, code: str, assignment_id: uuid.UUID, current_user: User
) -> VocabularyClassResults:
    """教师结果载荷（results 路由与 CSV 导出共用）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = _get_assignment(session, classroom.id, assignment_id)
    student_rows, word_rows = vocab_service.class_results(session, assignment)
    quiz_rounds_states = [r.status for r in student_rows]
    finished = (
        [r for r in student_rows if r.quiz_end_reason is not None]
        if assignment.mode == "quiz"
        else []
    )
    scores = [r.score for r in finished if r.score is not None]
    return VocabularyClassResults(
        assignment=_assignment_public(assignment),
        target_count=len(student_rows),
        completed_count=sum(1 for s in quiz_rounds_states if s == "completed"),
        in_progress_count=sum(1 for s in quiz_rounds_states if s == "in_progress"),
        not_started_count=sum(1 for s in quiz_rounds_states if s == "not_started"),
        timed_out_count=(
            sum(1 for r in finished if r.quiz_end_reason == "timeout")
            if assignment.mode == "quiz"
            else 0
        ),
        students=student_rows,
        words=word_rows,
        pass_line=assignment.pass_line if assignment.mode == "quiz" else None,
        passed_count=(
            sum(1 for s in scores if assignment.pass_line <= s)
            if assignment.mode == "quiz"
            else 0
        ),
        avg_score=(int(sum(scores) / len(scores) + 0.5) if scores else None)
        if assignment.mode == "quiz"
        else None,
        grades_published=assignment.grades_published_at is not None,
        answers_published=assignment.answers_published_at is not None,
    )
