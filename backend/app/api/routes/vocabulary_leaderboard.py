"""词汇学习（背单词）模块接口：班内词汇学习榜（#517）。

    GET  /classes/{code}/vocabulary/leaderboard/settings      教师/管理员读设置
    PUT  /classes/{code}/vocabulary/leaderboard/settings      教师/管理员改设置
    PUT  /classes/{code}/vocabulary/leaderboard/participation 学生加入/退出
    GET  /classes/{code}/vocabulary/leaderboard               榜单（学生/教师）

权限口径：课堂不存在/未入班先 404，成员身份不足再 403，最后才判 vocabulary
模块闸门（404 优先于 403，与既有词汇端点一致）。学生视角不可见（整班关闭或
仅教师可见）返回 403 ``leaderboard_unavailable``；教师设置页仍可 200 预览。
"""

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.classes import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
)
from app.models import (
    VocabularyLeaderboardSettings,
    VocabularyLeaderboardSettingsUpdate,
    VocabularyLeaderboardView,
    VocabularyParticipationState,
    VocabularyParticipationUpdate,
)
from app.services import vocabulary_leaderboard as service

router = APIRouter()


@router.get(
    "/classes/{code}/vocabulary/leaderboard/settings",
    response_model=VocabularyLeaderboardSettings,
)
def read_leaderboard_settings(
    session: SessionDep, code: str, current_user: CurrentUser
) -> Any:
    """榜单设置：仅本班授权教师（含共管）/本校管理员。无库行返回默认值。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user, "vocabulary")
    return service.settings_payload(service.get_setting(session, classroom.id))


@router.put(
    "/classes/{code}/vocabulary/leaderboard/settings",
    response_model=VocabularyLeaderboardSettings,
)
def update_leaderboard_settings(
    session: SessionDep,
    code: str,
    body: VocabularyLeaderboardSettingsUpdate,
    current_user: CurrentUser,
) -> Any:
    """更新榜单开关 / 可见范围 / 匿名口径（本班授权教师/本校管理员）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user, "vocabulary")
    row = service.update_setting(
        session, classroom.id, body, updated_by=current_user.id
    )
    return service.settings_payload(row)


@router.put(
    "/classes/{code}/vocabulary/leaderboard/participation",
    response_model=VocabularyParticipationState,
)
def update_participation(
    session: SessionDep,
    code: str,
    body: VocabularyParticipationUpdate,
    current_user: CurrentUser,
) -> Any:
    """学生加入 / 退出榜单；仅教师可见或整班关闭期间不允许加入（403）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user, "vocabulary")
    return service.set_participation(session, classroom.id, student, body.joined)


@router.get(
    "/classes/{code}/vocabulary/leaderboard",
    response_model=VocabularyLeaderboardView,
)
def read_leaderboard(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    week_start: date | None = Query(default=None),
) -> Any:
    """班内本周掌握词数榜；教师/本校管理员可查任意不晚于本周的周一，
    学生只能查不早于本人首次加入周。"""
    classroom = _get_classroom(session, code)
    if current_user.role == "student":
        student = _student_profile_of(session, classroom, current_user, "vocabulary")
        viewer = "student"
    else:
        _require_classroom_teacher(classroom, current_user, "vocabulary")
        student = None
        viewer = "teacher"
    week = service.resolve_week_start(week_start)
    return service.build_leaderboard(session, classroom.id, viewer, student, week)
