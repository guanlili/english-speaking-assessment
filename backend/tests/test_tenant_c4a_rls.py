"""多租户 C4a：RLS 策略落地验收（受限角色真实连接）。

验收点（A 期清单 §3 原型命题在应用测试库的重放，设计稿 §5）：
1. 32 张业务表全部 ENABLE+FORCE+策略 tenant_isolation；身份层/平台口径
   表不启。
2. 受限角色（NOSUPERUSER NOBYPASSRLS）真实连接：
   - 缺上下文默认拒绝（SELECT 空 / INSERT 被拒）——P1
   - tenant_scope 内只见本校行（ORM 路径同受约束）——P2a
   - WITH CHECK 拒绝跨租户写入——P2c
3. 平台角色（BYPASSRLS）无上下文可见全量——平台通道语义。
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from app.alembic.versions.b5d9e4f1a8c7_multi_tenant_c4a_rls_policies import (
    RLS_TABLES,
)
from app.core.config import settings
from app.core.tenant_context import install_tenant_bind, tenant_scope
from app.models import DEFAULT_TENANT_ID, Passage, Tenant

APP_ROLE = "esa_app_test"
APP_PASSWORD = "esa_app_test_pw"
PLATFORM_ROLE = "esa_platform_test"
PLATFORM_PASSWORD = "esa_platform_test_pw"

_tag = uuid.uuid4().hex[:8]


def _test_db_uri(user: str, password: str) -> str:
    return (
        f"postgresql+psycopg://{user}:{password}"
        f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}"
        f"/{settings.POSTGRES_DB_TEST}"
    )


@pytest.fixture(scope="module")
def admin_engine():
    """superuser 连接（策略与角色由 conftest 建表后统一铺设）；本 fixture
    只负责造数与 teardown 清理——**不得在此重铺策略**：模块中途的
    DROP/CREATE POLICY 要 ACCESS EXCLUSIVE 锁，会被前序模块遗留的
    idle-in-transaction 连接堵死（全量锁 15 分钟的根因）。"""
    engine = create_engine(
        str(settings.SQLALCHEMY_DATABASE_TEST_URI), poolclass=NullPool
    )
    yield engine
    with Session(engine) as s:
        s.connection().execute(
            text(f"DELETE FROM passage WHERE slug LIKE 'c4-{_tag}-%'")
        )
        s.connection().execute(text(f"DELETE FROM tenant WHERE slug = 'c4-{_tag}'"))
        s.commit()
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine_restricted(admin_engine):
    """受限角色引擎（装租户绑定：begin 事件 set_config）。"""
    engine = create_engine(_test_db_uri(APP_ROLE, APP_PASSWORD), poolclass=NullPool)
    install_tenant_bind(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def platform_engine_restricted(admin_engine):
    engine = create_engine(
        _test_db_uri(PLATFORM_ROLE, PLATFORM_PASSWORD), poolclass=NullPool
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def other_tenant(admin_engine) -> Iterator[uuid.UUID]:
    """第二租户（module 级复用；行由 admin_engine teardown 统一清）。"""
    with Session(admin_engine) as s:
        row = Tenant(slug=f"c4-{_tag}", name_zh="C4 乙校")
        s.add(row)
        s.commit()
        s.refresh(row)
        yield row.id


def test_policies_present(admin_engine) -> None:
    """32 表全部带 tenant_isolation 策略且 FORCE；user 表不启。"""
    with admin_engine.connect() as c:
        rows = (
            c.execute(
                text(
                    "SELECT tablename FROM pg_policies "
                    "WHERE schemaname='public' AND policyname='tenant_isolation'"
                )
            )
            .scalars()
            .all()
        )
        assert set(rows) == set(RLS_TABLES)
        forced = (
            c.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relrowsecurity "
                    "AND relforcerowsecurity AND relnamespace='public'::regnamespace"
                )
            )
            .scalars()
            .all()
        )
        assert set(RLS_TABLES) <= set(forced)
        # 身份层不启：user 表无策略
        user_rls = c.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE relname='user' AND relnamespace='public'::regnamespace"
            )
        ).scalar_one()
        assert user_rls is False


def test_rls_denies_without_context(
    app_engine_restricted, admin_engine, other_tenant
) -> None:
    """缺上下文默认拒绝：SELECT 空、INSERT 被策略拒（P1 同构）。"""
    with SASession(app_engine_restricted) as s:
        rows = s.execute(text("SELECT count(*) FROM passage")).scalar_one()
        assert rows == 0
        with pytest.raises(Exception, match="row-level security"):
            s.add(Passage(title="拒", text="x", slug=f"c4-{_tag}-deny"))
            s.commit()
        s.rollback()


def test_rls_scopes_reads_and_blocks_cross_tenant_write(
    app_engine_restricted, admin_engine, other_tenant
) -> None:
    """上下文内只见本校；WITH CHECK 拒跨租户写（P2a/P2c 同构）。"""
    slug_a, slug_b = f"c4-{_tag}-a", f"c4-{_tag}-b"
    with Session(admin_engine) as s:  # superuser 造两校数据
        s.add(Passage(title="甲校", text="a", slug=slug_a))
        s.add(Passage(title="乙校", text="b", slug=slug_b, tenant_id=other_tenant))
        s.commit()

    # 事务级绑定：set_config 随事务存活——每个 scope 块独立事务
    # （块前 commit 结束上一事务，新事务 begin 事件按当前上下文重绑）
    with SASession(app_engine_restricted) as s:
        with tenant_scope(DEFAULT_TENANT_ID):
            seen = s.execute(text("SELECT slug FROM passage")).scalars().all()
            assert slug_a in seen and slug_b not in seen
        s.commit()
        with tenant_scope(other_tenant):
            seen = s.execute(text("SELECT slug FROM passage")).scalars().all()
            assert slug_b in seen and slug_a not in seen
        s.commit()
        # 甲校上下文写乙校租户行：WITH CHECK 拒绝（P2c 同构）
        with tenant_scope(DEFAULT_TENANT_ID):
            with pytest.raises(Exception, match="row-level security"):
                s.add(
                    Passage(
                        title="跨校写",
                        text="x",
                        slug=f"c4-{_tag}-cross",
                        tenant_id=other_tenant,
                    )
                )
                s.commit()
            s.rollback()


def test_platform_role_bypasses_rls(platform_engine_restricted, admin_engine) -> None:
    """平台角色（BYPASSRLS）无上下文可见全量——平台通道语义。"""
    with SASession(platform_engine_restricted) as s:
        count = s.execute(
            text(f"SELECT count(*) FROM passage WHERE slug LIKE 'c4-{_tag}-%'")
        ).scalar_one()
        assert count >= 2  # 两校行都可见（上测试造的 a/b）
