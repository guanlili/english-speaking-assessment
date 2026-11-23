"""当前学校用户可见的已购模块清单（#516 / #517）。

学校用户登录后拉取本校已生效模块，前端据此装配导航与入口；平台运营
身份不走本端点（运营没有"本校模块"概念）。清单口径与服务端闸门一致：
缺行/关闭/未到生效时间均不计入。
"""

from typing import Any

from fastapi import APIRouter
from sqlmodel import SQLModel

from app.api.deps import CurrentUser, SessionDep
from app.services import entitlement

router = APIRouter(tags=["modules"])


class ModulesMe(SQLModel):
    modules: list[str]


@router.get("/modules/me", response_model=ModulesMe)
def read_modules_me(session: SessionDep, current_user: CurrentUser) -> Any:
    return ModulesMe(
        modules=entitlement.list_enabled_modules(session, current_user.tenant_id)
    )
