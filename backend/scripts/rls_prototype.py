"""多租户 A 期 · RLS + 连接池原型（ TenantSession 行为验证）.

在独立原型库（rls_proto）上验证 V1.0/设计稿 §5.3 的四个关键命题，结果
记入 docs/multi-tenant-a-inventory.md「原型验证结论」：

  P1 缺上下文默认拒绝：运行角色未 set_config 时 SELECT 空、INSERT 被拒
  P2 事务级绑定：ORM 与裸 connection().execute 两类路径同受 RLS 约束；
     WITH CHECK 拒绝跨租户写入
  P3 连接复用不串校：同一物理连接先后服务租户 A/B（commit 后新事务
     重绑），无跨租户残留（transaction-local set_config 语义）
  P4 双角色分离：DDL 角色可建表（Alembic 通道），运行角色无 DDL 权限、
     非 owner、无 BYPASSRLS；FOR UPDATE SKIP LOCKED 领取语义在 RLS 下保持

用法（本地栈，db 在 5433）：
  POSTGRES_SERVER=localhost POSTGRES_PORT=5433 uv run python scripts/rls_prototype.py
幂等：每次运行重建原型库与角色，结束即清理，不触碰 app/app_test。
"""

import os
import sys
import uuid
from contextvars import ContextVar

import sqlalchemy
import sqlalchemy.event
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings

RESULTS: list[tuple[str, bool, str]] = []


def check(pid: str, ok: bool, note: str = "") -> None:
    RESULTS.append((pid, ok, note))
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {pid}  {note}")


def admin_engine():
    dsn = (
        f"postgresql+psycopg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{os.environ.get('POSTGRES_SERVER', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5433')}/postgres"
    )
    return create_engine(
        dsn, isolation_level="AUTOCOMMIT", poolclass=sqlalchemy.pool.NullPool
    )


TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
DDL_ROLE = "esa_ddl_proto"
APP_ROLE = "esa_app_proto"


def setup_proto(admin) -> None:
    """DDL 角色建库建表 → 种子数据 → 启用 FORCE RLS → 授权运行角色。"""
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS rls_proto WITH (FORCE)"))
        for role in (APP_ROLE, DDL_ROLE):
            c.execute(text(f"DROP ROLE IF EXISTS {role}"))
        c.execute(text(f"CREATE ROLE {DDL_ROLE} LOGIN PASSWORD 'ddl_proto'"))
        c.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD 'app_proto'"))
        c.execute(text(f"CREATE DATABASE rls_proto OWNER {DDL_ROLE}"))

    ddl_dsn = (
        f"postgresql+psycopg://{DDL_ROLE}:ddl_proto"
        f"@{os.environ.get('POSTGRES_SERVER', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5433')}/rls_proto"
    )
    ddl = create_engine(ddl_dsn, poolclass=sqlalchemy.pool.NullPool)
    with ddl.begin() as c:
        c.execute(
            text("""
            CREATE TABLE proto_row (
                id uuid PRIMARY KEY,
                tenant_id uuid NOT NULL,
                name text NOT NULL
            )
        """)
        )
        # 先种子后启用 RLS：owner 在 FORCE 前不受策略约束
        for tid, label in ((TENANT_A, "A1"), (TENANT_A, "A2"), (TENANT_B, "B1")):
            c.execute(
                text("INSERT INTO proto_row (id, tenant_id, name) VALUES (:i, :t, :n)"),
                {"i": str(uuid.uuid4()), "t": tid, "n": label},
            )
        # RLS：读删 USING、写改 WITH CHECK；未设上下文（NULL/''）时永不匹配 → 默认拒绝
        policy = """
            ALTER TABLE proto_row ENABLE ROW LEVEL SECURITY;
            ALTER TABLE proto_row FORCE ROW LEVEL SECURITY;
            CREATE POLICY proto_tenant_isolation ON proto_row
                USING (coalesce(current_setting('app.tenant_id', true), '')
                       = tenant_id::text)
                WITH CHECK (coalesce(current_setting('app.tenant_id', true), '')
                       = tenant_id::text)
        """
        c.execute(text(policy))
        c.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        c.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON proto_row TO {APP_ROLE}")
        )
    ddl.dispose()


def app_engine():
    dsn = (
        f"postgresql+psycopg://{APP_ROLE}:app_proto"
        f"@{os.environ.get('POSTGRES_SERVER', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5433')}/rls_proto"
    )
    # 单连接池：P3 连接复用验证的前提（同一物理连接先后服务两个租户）
    return create_engine(dsn, pool_size=1, max_overflow=0)


def main() -> int:
    admin = admin_engine()
    setup_proto(admin)
    # TenantSession 原型：contextvar + 引擎事务事件，每次新事务重绑
    tenant_ctx: ContextVar[str | None] = ContextVar("tenant_ctx", default=None)
    engine = app_engine()

    @sqlalchemy.event.listens_for(engine, "begin")
    def _bind_tenant(conn):
        tid = tenant_ctx.get()
        if tid is not None:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid}
            )

    # ── P1 缺上下文默认拒绝 ──
    with Session(engine) as s:
        rows = s.execute(text("SELECT count(*) FROM proto_row")).scalar_one()
        check("P1a 无上下文 SELECT 空", rows == 0, f"count={rows}")
        try:
            s.execute(
                text("INSERT INTO proto_row VALUES (:i, :t, :n)"),
                {"i": str(uuid.uuid4()), "t": TENANT_A, "n": "X"},
            )
            s.flush()
            check("P1b 无上下文 INSERT 被拒", False, "竟然写入成功")
        except Exception as exc:  # noqa: BLE001 - 策略违反即预期
            s.rollback()
            check(
                "P1b 无上下文 INSERT 被拒",
                "row-level security" in str(exc),
                str(exc)[:80],
            )

    # ── P2 事务级绑定：ORM 与裸 connection 双路径 + WITH CHECK ──
    token = tenant_ctx.set(TENANT_A)
    with Session(engine) as s:
        names = [
            r[0]
            for r in s.execute(text("SELECT name FROM proto_row ORDER BY name")).all()
        ]
        check("P2a ORM-文本查询按租户过滤", names == ["A1", "A2"], f"names={names}")
        # 裸 Core select 走 connection().execute（usage_export 同款路径）
        from sqlalchemy import column, table

        proto = table("proto_row", column("name"))
        raw = [
            r[0]
            for r in s.connection()
            .execute(sqlalchemy.select(proto.c.name).order_by(proto.c.name))
            .all()
        ]
        check("P2b 裸 connection().execute 同样过滤", raw == ["A1", "A2"], f"raw={raw}")
        try:
            s.execute(
                text("INSERT INTO proto_row VALUES (:i, :t, :n)"),
                {"i": str(uuid.uuid4()), "t": TENANT_B, "n": "跨租户写入"},
            )
            s.flush()
            check("P2c WITH CHECK 拒绝跨租户写入", False, "竟然写入成功")
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            check(
                "P2c WITH CHECK 拒绝跨租户写入",
                "violates row-level security" in str(exc),
                str(exc)[:80],
            )
    tenant_ctx.reset(token)

    # ── P3 连接复用不串校（同一物理连接先后服务 A/B） ──
    token = tenant_ctx.set(TENANT_A)
    with Session(engine) as s:
        pid_a = s.execute(text("SELECT pg_backend_pid()")).scalar_one()
        n_a = s.execute(text("SELECT count(*) FROM proto_row")).scalar_one()
    tenant_ctx.reset(token)
    token = tenant_ctx.set(TENANT_B)
    with Session(engine) as s:
        pid_b = s.execute(text("SELECT pg_backend_pid()")).scalar_one()
        names_b = [r[0] for r in s.execute(text("SELECT name FROM proto_row")).all()]
        # 新事务内旧值已失效（transaction-local 语义的另一半）
        stale = s.execute(
            text("SELECT coalesce(current_setting('app.tenant_id', true), '')")
        ).scalar_one()
    tenant_ctx.reset(token)
    check(
        "P3a 同一物理连接 A→B",
        pid_a == pid_b,
        f"backend_pid {pid_a}=={pid_b}",
    )
    check(
        "P3b 复用后只见 B 行",
        names_b == ["B1"] and n_a == 2,
        f"A 事务 count={n_a}，B 事务 names={names_b}",
    )
    check(
        "P3c 事务结束后租户设置不残留", stale == TENANT_B, "当前事务值为 B（重绑生效）"
    )

    # ── P4 双角色 + SKIP LOCKED ──
    app = create_engine(
        f"postgresql+psycopg://{APP_ROLE}:app_proto"
        f"@{os.environ.get('POSTGRES_SERVER', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5433')}/rls_proto",
        poolclass=sqlalchemy.pool.NullPool,
    )
    with app.connect() as c:
        bypass = c.execute(
            text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = :r"),
            {"r": APP_ROLE},
        ).one()
        check(
            "P4a 运行角色无 superuser/BYPASSRLS",
            not bypass[0] and not bypass[1],
            f"bypassrls={bypass[0]} super={bypass[1]}",
        )
        try:
            c.execute(text("CREATE TABLE should_fail (id int)"))
            check("P4b 运行角色无 DDL 权限", False, "竟然建表成功")
        except Exception as exc:  # noqa: BLE001
            check(
                "P4b 运行角色无 DDL 权限",
                "permission denied" in str(exc),
                str(exc)[:60],
            )
    app.dispose()

    ddl2 = create_engine(
        f"postgresql+psycopg://{DDL_ROLE}:ddl_proto"
        f"@{os.environ.get('POSTGRES_SERVER', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5433')}/rls_proto",
        poolclass=sqlalchemy.pool.NullPool,
    )
    with ddl2.connect() as c:
        c.execute(text("CREATE TABLE ddl_channel_ok (id int)"))
        check("P4c DDL 角色可建表（Alembic 通道）", True, "CREATE TABLE 成功")
    ddl2.dispose()

    # SKIP LOCKED 领取（评分 worker 同款语义）在 RLS 下保持
    # 双连接专用引擎：主引擎是单连接池（P3 复用验证前提），并发领取需要两条
    token = tenant_ctx.set(TENANT_A)
    lock_engine = create_engine(
        f"postgresql+psycopg://{APP_ROLE}:app_proto"
        f"@{os.environ.get('POSTGRES_SERVER', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5433')}/rls_proto",
        pool_size=2,
        max_overflow=0,
    )

    @sqlalchemy.event.listens_for(lock_engine, "begin")
    def _bind_tenant_lock(conn):
        tid = tenant_ctx.get()
        if tid is not None:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid}
            )

    c1 = lock_engine.connect()
    c2 = lock_engine.connect()
    t1 = c1.begin()
    t2 = c2.begin()
    c1.execute(text("SET LOCAL lock_timeout = '2s'"))
    r1 = c1.execute(
        text("SELECT name FROM proto_row ORDER BY name LIMIT 1 FOR UPDATE SKIP LOCKED")
    ).all()
    r2 = c2.execute(
        text("SELECT name FROM proto_row ORDER BY name LIMIT 1 FOR UPDATE SKIP LOCKED")
    ).all()
    t1.rollback()
    t2.rollback()
    c1.close()
    c2.close()
    lock_engine.dispose()
    tenant_ctx.reset(token)
    check(
        "P4d FOR UPDATE SKIP LOCKED 在 RLS 下不重复领取",
        r1 == [("A1",)] and r2 == [("A2",)],
        f"t1={r1} t2={r2}",
    )

    # 清理
    engine.dispose()
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS rls_proto WITH (FORCE)"))
        for role in (APP_ROLE, DDL_ROLE):
            c.execute(text(f"DROP ROLE IF EXISTS {role}"))
    admin.dispose()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n原型结论：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
