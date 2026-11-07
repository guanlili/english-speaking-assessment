"""词汇学习（背单词）模块接口：quiz 域。

由原 vocabulary.py 按域拆出：端点路径、参数、响应模型与实现均未改动。

    /vocabulary/books                 词库 CRUD + 词库内加词（教师/管理员）
    /vocabulary/books/import-preview  CSV 解析预览（不落库）
    /vocabulary/words/{id}            词条编辑
    /classes/{code}/vocabulary/...    课堂发布 / 学生任务 / 结果 / 错词本
    /vocabulary/sessions/{id}/answers 学生作答（服务端判分）

权限口径（设计文档 §5）：词库编辑/发布 = 课堂所有者教师或管理员；
学生任务仅目标名单内的本班学生；原始作答仅本人与该班教师可读。
401 只表示登录失效；权限不足一律 403。
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlmodel import col, select

from app.api.deps import SessionDep, TeacherUserDep
from app.api.routes.classes import (
    _get_classroom,
    _require_classroom_teacher,
)
from app.api.routes.vocabulary_shared import (
    _csv_text_cell,
    _get_quiz_assignment,
    read_vocab_results_payload,
)
from app.models import (
    VocabularyAssignmentTarget,
    VocabularySession,
    VocabularyStudentPlan,
    get_datetime_utc,
)
from app.services import vocabulary as vocab_service

router = APIRouter()


@router.post("/classes/{code}/vocabulary/assignments/{assignment_id}/publish-grades")
def publish_quiz_grades(
    session: SessionDep,
    code: str,
    assignment_id: uuid.UUID,
    current_user: TeacherUserDep,
) -> Any:
    """公布测验成绩：未公布前学生只能看到提交状态（幂等，可重复调用）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = _get_quiz_assignment(session, classroom.id, assignment_id)
    if assignment.grades_published_at is None:
        assignment.grades_published_at = get_datetime_utc()
        session.add(assignment)
        session.commit()
    return {
        "message": "测验成绩已公布",
        "grades_published_at": assignment.grades_published_at,
    }


@router.post("/classes/{code}/vocabulary/assignments/{assignment_id}/publish-answers")
def publish_quiz_answers(
    session: SessionDep,
    code: str,
    assignment_id: uuid.UUID,
    current_user: TeacherUserDep,
) -> Any:
    """公布测验答案：答卷揭示拼写与对错，错词进入错词本（独立于成绩公布）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = _get_quiz_assignment(session, classroom.id, assignment_id)
    if assignment.answers_published_at is None:
        assignment.answers_published_at = get_datetime_utc()
        session.add(assignment)
        session.commit()
    return {
        "message": "测验答案已公布",
        "answers_published_at": assignment.answers_published_at,
    }


@router.post(
    "/classes/{code}/vocabulary/assignments/{assignment_id}/students/{student_id}/grant-retake"
)
def grant_quiz_retake(
    session: SessionDep,
    code: str,
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    current_user: TeacherUserDep,
) -> Any:
    """单独授权一次补考：该学生可再开一份答卷（原答卷保留）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = _get_quiz_assignment(session, classroom.id, assignment_id)
    target = session.exec(
        select(VocabularyAssignmentTarget).where(
            VocabularyAssignmentTarget.assignment_id == assignment.id,  # type: ignore[arg-type]
            VocabularyAssignmentTarget.student_id == student_id,  # type: ignore[arg-type]
        )
    ).first()
    if target is None:
        raise HTTPException(status_code=404, detail="该学生不在此测验的名单内")
    if target.retake_granted_at is None:
        target.retake_granted_at = get_datetime_utc()
        session.add(target)
        session.commit()
    return {"message": "已授权补考一次", "retake_granted_at": target.retake_granted_at}


@router.get(
    "/classes/{code}/vocabulary/assignments/{assignment_id}/students/{student_id}/answer-sheet",
    response_model=VocabularyStudentPlan,
)
def read_quiz_answer_sheet(
    session: SessionDep,
    code: str,
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    current_user: TeacherUserDep,
    round_no: int | None = None,
) -> Any:
    """教师查看学生答卷（不受公布规则约束，全量揭示；默认最新一份答卷）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = _get_quiz_assignment(session, classroom.id, assignment_id)
    rounds = session.exec(
        select(VocabularySession)
        .where(
            VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            col(VocabularySession.quiz_started_at).is_not(None),  # type: ignore[union-attr]
        )
        .order_by(col(VocabularySession.round_no))
    ).all()
    if round_no is not None:
        vocab_session = next((r for r in rounds if r.round_no == round_no), None)
    else:
        vocab_session = rounds[-1] if rounds else None
    if vocab_session is None:
        raise HTTPException(status_code=404, detail="该学生还没有答卷")
    return vocab_service.student_plan(session, vocab_session, reveal=True)


@router.get("/classes/{code}/vocabulary/assignments/{assignment_id}/results-export")
def export_quiz_results(
    session: SessionDep,
    code: str,
    assignment_id: uuid.UUID,
    current_user: TeacherUserDep,
) -> Any:
    """导出测验成绩 CSV（固定应考名单 + 状态/成绩/切屏等，UTF-8 BOM 兼容 Excel）。

    用户可控文本单元格经 _csv_text_cell 防公式注入（与前端 csv.ts 同规则）。
    """
    import csv
    import io

    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = _get_quiz_assignment(session, classroom.id, assignment_id)
    results = read_vocab_results_payload(session, code, assignment_id, current_user)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "姓名",
            "状态",
            "成绩",
            "及格",
            "答对",
            "答错",
            "未答",
            "有效轮次",
            "参与次数",
            "切屏次数",
            "终结方式",
            "交卷/结束时间",
        ]
    )
    status_labels = {
        "not_started": "未开始",
        "in_progress": "进行中",
        "completed": "已交卷" if assignment.mode == "quiz" else "已完成",
    }
    for row in results.students:
        end_label = ""
        if row.quiz_end_reason == "timeout":
            end_label = "超时结束"
        elif row.quiz_end_reason == "manual":
            end_label = "主动交卷"
        writer.writerow(
            [
                _csv_text_cell(row.display_name),
                _csv_text_cell(
                    status_labels.get(row.status, row.status)
                    + (f"（{end_label}）" if end_label else "")
                ),
                row.score if row.score is not None else "",
                ("是" if row.passed else "否") if row.passed is not None else "",
                row.correct_first_count,
                max(0, row.answered_count - row.correct_first_count),
                max(0, row.total_count - row.answered_count),
                row.effective_round_no if row.effective_round_no is not None else "",
                row.attempt_count,
                row.tab_switch_count,
                end_label,
                row.submitted_at or "",
            ]
        )
    buffer.seek(0)
    filename = f"quiz-v{assignment.version_no}-{classroom.code}.csv"
    return Response(
        content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
