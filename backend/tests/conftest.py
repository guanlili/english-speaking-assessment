import os
from collections.abc import Generator

# 必须在导入 app 之前设置：测试永远跑 mock 引擎，不读本地 .env 的
# SCORING_PROVIDER（开发者本机切 ark 后，测试不能变成真调付费云 API）
os.environ["SCORING_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, delete

from app.api.deps import get_db
from app.api.routes.utils import get_readiness_dsn
from app.core.config import settings
from app.core.db import init_db
from app.main import app
from app.models import (
    AdminMetricsDaily,
    Attempt,
    ChangelogEntry,
    Classroom,
    Passage,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    SentenceFrame,
    Student,
    StudentBadge,
    StudentFrameFavorite,
    Unit,
    User,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularyBook,
    VocabularyBookItem,
    VocabularyLevelEntry,
    VocabularySession,
    VocabularyWord,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


def _create_test_database() -> Engine:
    """确保测试库存在（幂等）。连接同一实例的管理库 postgres 执行 CREATE DATABASE。

    本地与 CI 零配置一致：postgres 镜像只自动创建 POSTGRES_DB 一个库，
    测试库由这里按需创建，避免在 CI 或本地再手维护一个建库步骤。
    """
    admin_uri = (
        str(settings.SQLALCHEMY_DATABASE_TEST_URI).rsplit("/", 1)[0] + "/postgres"
    )
    admin_engine = create_engine(
        admin_uri, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    with admin_engine.connect() as conn:
        # 每轮 drop+recreate：CI 重跑时 PG 服务容器复用，上一轮残留的
        # 共享测试库数据（尤其多租户 B2 的跨租户同号用户）会让超管全局
        # 登录命中歧义拒绝——脏数据是 KeyError: 'access_token' 的根因
        conn.execute(
            text(f'DROP DATABASE IF EXISTS "{settings.POSTGRES_DB_TEST}" WITH (FORCE)')
        )
        conn.execute(text(f'CREATE DATABASE "{settings.POSTGRES_DB_TEST}"'))
    admin_engine.dispose()
    from app.core.tenant_context import install_tenant_bind

    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    # 与生产引擎同款租户事务绑定（C3）：测试里的 tenant_scope 语义与线上一致
    install_tenant_bind(engine)
    return engine


def _setup_rls_and_roles(engine) -> None:
    """多租户 C4a：建表后立刻铺 RLS 策略与受限角色（此刻无并发连接，
    ALTER TABLE 的 ACCESS EXCLUSIVE 锁不会与 session 级 db fixture 的
    idle-in-transaction 连接互堵——测试中途铺设曾把全量锁死 15 分钟）。

    与迁移 b5d9e4f1a8c7 同语句；角色是集群级对象，幂等创建。
    """
    from app.alembic.versions.b5d9e4f1a8c7_multi_tenant_c4a_rls_policies import (
        POLICY,
        RLS_TABLES,
    )

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        # ALTER/DROP POLICY 要 ACCESS EXCLUSIVE 锁：任何挂在 app_test 上的
        # idle-in-transaction 连接（上一轮被杀进程的遗留、或在途模块的
        # 活事务）都会把铺设死锁。测试库独占，先清场再拿锁；
        # lock_timeout 兜底防无限等待
        c.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        c.execute(text("SET lock_timeout = '10s'"))
        for table in RLS_TABLES:
            c.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
            c.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            c.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            c.execute(
                text(
                    f"CREATE POLICY tenant_isolation ON {table} "
                    f"USING ({POLICY}) WITH CHECK ({POLICY})"
                )
            )
        for role, pw in [
            ("esa_app_test", "esa_app_test_pw"),
            ("esa_platform_test", "esa_platform_test_pw"),
        ]:
            c.execute(
                text(
                    f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles "
                    f"WHERE rolname = '{role}') THEN "
                    f"CREATE ROLE {role} LOGIN PASSWORD '{pw}'; END IF; END $$"
                )
            )
        c.execute(
            text(
                "ALTER ROLE esa_app_test NOSUPERUSER NOBYPASSRLS "
                "NOCREATEROLE NOCREATEDB"
            )
        )
        c.execute(text("ALTER ROLE esa_platform_test NOSUPERUSER BYPASSRLS"))
        for role in ("esa_app_test", "esa_platform_test"):
            c.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            c.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    f"IN SCHEMA public TO {role}"
                )
            )
            c.execute(text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {role}"))


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    # 安全兜底 1：禁止在非 local 环境运行测试
    if settings.ENVIRONMENT != "local":
        raise RuntimeError(
            f"Refusing to run tests in ENVIRONMENT={settings.ENVIRONMENT}. "
            "Set ENVIRONMENT=local to run tests."
        )
    # 安全兜底 2：测试库绝不能指向开发/生产库（会清空其数据）。
    # 必须发生在任何建库、建表或删除操作之前。
    test_uri = str(settings.SQLALCHEMY_DATABASE_TEST_URI)
    if test_uri == str(settings.SQLALCHEMY_DATABASE_URI):
        raise RuntimeError(
            f"Refusing to run tests: POSTGRES_DB_TEST ({settings.POSTGRES_DB_TEST}) "
            f"points at the application database ({settings.POSTGRES_DB}). "
            "Tests DELETE all rows — set POSTGRES_DB_TEST to a dedicated database."
        )
    engine = _create_test_database()
    # 测试库独立于 Alembic 迁移直接建表（模板测试不需要迁移链），
    # checkfirst 保证重复运行安全
    SQLModel.metadata.create_all(engine)
    # 多租户 C4a：建表后无并发连接的窗口铺 RLS 策略与受限角色
    _setup_rls_and_roles(engine)

    # 全局 engine 覆盖：worker、startup_recovery、get_db 依赖全部使用测试库
    # （core.db.__getattr__ 动态返回覆盖引擎，避免任何模块级 import 拿到开发库）
    from app.core.db import set_engine

    set_engine(engine)

    # 关闭生命周期中由 worker 模块可能启动的全局线程池（测试结束时不残留）
    def _override_get_db() -> Generator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_readiness_dsn] = lambda: test_uri.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )

    with Session(engine) as session:
        init_db(session)
        yield session
        # 清理测试库数据（独立库内，无开发数据风险；按外键依赖倒序）
        from app.models import ExportAudit, ExportJob

        session.exec(delete(ExportAudit))  # type: ignore[call-overload]
        session.exec(delete(ExportJob))  # type: ignore[call-overload]
        session.exec(delete(ChangelogEntry))  # type: ignore[call-overload]
        session.exec(delete(StudentFrameFavorite))  # type: ignore[call-overload]
        session.exec(delete(SentenceFrame))  # type: ignore[call-overload]
        session.exec(delete(VocabularyLevelEntry))  # type: ignore[call-overload]
        session.exec(delete(VocabularyAnswer))  # type: ignore[call-overload]
        session.exec(delete(VocabularySession))  # type: ignore[call-overload]
        session.exec(delete(VocabularyAssignmentTarget))  # type: ignore[call-overload]
        session.exec(delete(VocabularyAssignment))  # type: ignore[call-overload]
        session.exec(delete(VocabularyBookItem))  # type: ignore[call-overload]
        session.exec(delete(VocabularyBook))  # type: ignore[call-overload]
        session.exec(delete(VocabularyWord))  # type: ignore[call-overload]
        session.exec(delete(AdminMetricsDaily))  # type: ignore[call-overload]
        from app.models import AdminCostReconcile

        session.exec(delete(AdminCostReconcile))  # type: ignore[call-overload]
        session.exec(delete(Attempt))  # type: ignore[call-overload]
        session.exec(delete(PracticeSession))  # type: ignore[call-overload]
        session.exec(delete(StudentBadge))  # type: ignore[call-overload]
        session.exec(delete(Student))  # type: ignore[call-overload]
        session.exec(delete(Classroom))  # type: ignore[call-overload]
        session.exec(delete(ScenarioQuestion))  # type: ignore[call-overload]
        session.exec(delete(Scenario))  # type: ignore[call-overload]
        session.exec(delete(RepeatSentence))  # type: ignore[call-overload]
        session.exec(delete(Passage))  # type: ignore[call-overload]
        session.exec(delete(Unit))  # type: ignore[call-overload]
        session.exec(delete(User))  # type: ignore[call-overload]
        session.commit()

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_readiness_dsn, None)

    # 关闭 worker/feedback 线程池（防止测试进程结束前线程仍在跑 / 持连接）
    try:
        from app.scoring import worker as _worker_mod

        _worker_mod.shutdown_executor()
    except Exception:  # pragma: no cover - 清理阶段兜底
        pass
    try:
        from app.exporting import worker as _export_worker

        _export_worker.stop_sweeper()
        _export_worker.shutdown_executor()
    except Exception:  # pragma: no cover - 清理阶段兜底
        pass

    set_engine(None)
    engine.dispose()


# 登录限流器为应用全局态（10 次/300s，IP 桶只按失败累积）：负向登录
# 测试的失败计数会跨模块累积，把后续模块 fixture 的正常登录顶到 429
# （B3 全量曾因 +1 个故意失败登录触发）。每个用例前后清零，测试间不共享。
@pytest.fixture(autouse=True)
def _reset_login_rate_limiter() -> Generator[None]:
    from app.api.routes.login import _login_attempts

    _login_attempts.clear()
    yield
    _login_attempts.clear()


# db 为 session 级 autouse fixture，pytest 保证它先于 module 级的 client 实例化
# （dependency_overrides 在 TestClient 发出任何请求前已注册）
@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def operator_token_headers(client: TestClient) -> dict[str, str]:
    """平台运营 token（B3）：平台路由专用——用户/大盘/目录/更新日志写。"""
    from tests.utils.utils import get_operator_token_headers

    return get_operator_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
