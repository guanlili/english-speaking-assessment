"""多租户 C4b：受限/平台数据库角色的幂等管理（prestart 在 Alembic 之后调用）。

职责（全部幂等，可重复执行）：
1. 按 env 建角色并同步属性与密码：
   - esa_app（APP_POSTGRES_USER/PASSWORD）：NOSUPERUSER NOBYPASSRLS
     NOCREATEROLE NOCREATEDB——业务受限角色，RLS 对其完全生效
   - esa_platform（PLATFORM_POSTGRES_USER/PASSWORD）：NOSUPERUSER
     BYPASSRLS——平台通道（跨租户口径）
2. GRANT：SCHEMA USAGE + 全部表 DML + 全部序列 USAGE——放在 Alembic
   之后跑，保证新迁移建的表也被授权（每次部署重放）。

密码未配（开发/CI 形态）→ 跳过建角色（不激活，连接回落 owner）。
用 admin/owner 连接执行（CREATEROLE 与对象授权都要求 owner 以上权限）。
"""

import logging
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _ensure_role(conn: Any, role: str, password: str, *, bypass: bool) -> None:
    # 纯属性片段（CREATE 与 ALTER 共用，均合法跟在角色名后）
    attrs = (
        "NOSUPERUSER "
        f"{'BYPASSRLS' if bypass else 'NOBYPASSRLS'} "
        "NOCREATEROLE NOCREATEDB LOGIN"
    )
    exists = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
    ).scalar()
    if exists:
        conn.execute(text(f"ALTER ROLE {role} {attrs}"))
        conn.execute(text(f"ALTER ROLE {role} LOGIN PASSWORD '{password}'"))
        logger.info("role %s attributes/password synced", role)
    else:
        # attrs 已含 LOGIN——CREATE 里不重复声明（PG 报冗余选项）
        conn.execute(text(f"CREATE ROLE {role} PASSWORD '{password}' {attrs}"))
        logger.info("role %s created", role)


def _grant(conn: Any, role: str) -> None:
    conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
    conn.execute(
        text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
            f"IN SCHEMA public TO {role}"
        )
    )
    conn.execute(text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {role}"))


def main() -> None:
    app_user = settings.APP_POSTGRES_USER
    app_pw = settings.APP_POSTGRES_PASSWORD
    platform_user = settings.PLATFORM_POSTGRES_USER
    platform_pw = settings.PLATFORM_POSTGRES_PASSWORD

    if not (app_user and app_pw) and not (platform_user and platform_pw):
        logger.info(
            "APP/PLATFORM DB credentials not configured — "
            "restricted roles skipped (owner fallback, RLS not enforced)"
        )
        return

    engine = create_engine(
        str(settings.SQLALCHEMY_ADMIN_DATABASE_URI), poolclass=NullPool
    )
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            if app_user and app_pw:
                _ensure_role(conn, app_user, app_pw, bypass=False)
                _grant(conn, app_user)
            if platform_user and platform_pw:
                _ensure_role(conn, platform_user, platform_pw, bypass=True)
                _grant(conn, platform_user)
    finally:
        engine.dispose()
    logger.info("database roles ensured")


if __name__ == "__main__":
    main()
