"""专注农场接口：地块状态只读视图与收获入账。

路径前缀 `/classes/{code}/vocabulary/student/farm`。

权限口径（设计稿 §4）：
- 仅本课堂学生可读/收获；跨班访问 404，不泄露地块存在性。
- 地块按登录账号跨班连续；XP 写当前课堂档案 ``student.xp``，streak 不动。
- 不做商家式排行榜、不做停留时长推断；农场奖励不计入教师任务统计。
"""

from typing import Any

from fastapi import APIRouter

from app.api.deps import SessionDep, StudentUserDep
from app.api.routes.classes import (
    _get_classroom,
    _student_profile_of,
)
from app.models import FarmHarvestResult, FarmView
from app.services import vocabulary_farm as farm_service

router = APIRouter()


@router.get(
    "/classes/{code}/vocabulary/student/farm",
    response_model=FarmView,
)
def read_farm(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
) -> Any:
    """农场视图：四阶段成长、今日有效练习、XP 余额、streak 与徽章来源。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    return farm_service.plot_view(session, student=student, user_id=current_user.id)


@router.post(
    "/classes/{code}/vocabulary/student/farm/harvest",
    response_model=FarmHarvestResult,
)
def harvest_farm(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
) -> Any:
    """成熟地块收获：+10 XP 入既有账本；未成熟/今日 XP 达上限 → 422。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    return farm_service.harvest(session, student=student, user_id=current_user.id)
