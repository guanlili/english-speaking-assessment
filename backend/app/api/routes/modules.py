"""当前学校用户可见的已购模块清单（#516 / #517）。

学校用户登录后拉取本校已生效模块，前端据此装配导航与入口；平台运营
身份不走本端点（运营没有"本校模块"概念）。清单口径与服务端闸门一致：
缺行/关闭/未到生效时间/已过期均不计入 ``modules``。

``statuses`` 对 speaking / vocabulary 两键都给出行级状态（缺行也返回
``not_granted`` 行，不 404），仅供学校管理员前端做 30/7/1 天到期提醒；
本端点只读，不提供任何写接口。
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from sqlmodel import SQLModel

from app.api.deps import CurrentUser, SessionDep
from app.services import entitlement

router = APIRouter(tags=["modules"])


class ModuleStatus(SQLModel):
    """单行模块授权的状态快照（与服务端闸门同一状态机口径）。"""

    module_key: str
    state: str
    enabled: bool
    effective_at: datetime | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    grant_type: str
    days_left: int | None = None
    granted_by: uuid.UUID | None = None


class ModulesMe(SQLModel):
    modules: list[str]
    statuses: list[ModuleStatus]


@router.get("/modules/me", response_model=ModulesMe)
def read_modules_me(session: SessionDep, current_user: CurrentUser) -> Any:
    statuses = [
        ModuleStatus(**status)
        for status in entitlement.list_statuses(session, current_user.tenant_id)
    ]
    return ModulesMe(
        modules=entitlement.list_enabled_modules(session, current_user.tenant_id),
        statuses=statuses,
    )
