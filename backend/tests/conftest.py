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
    Attempt,
    Classroom,
    Passage,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Student,
    StudentBadge,
    Unit,
    User,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularyBook,
    VocabularyBookItem,
    VocabularySession,
    VocabularyWord,
    WordlistEntry,
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
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": settings.POSTGRES_DB_TEST},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.POSTGRES_DB_TEST}"'))
    admin_engine.dispose()
    return create_engine(str(settings.SQLALCHEMY_DATABASE_TEST_URI))


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
        session.exec(delete(VocabularyAnswer))  # type: ignore[call-overload]
        session.exec(delete(VocabularySession))  # type: ignore[call-overload]
        session.exec(delete(VocabularyAssignmentTarget))  # type: ignore[call-overload]
        session.exec(delete(VocabularyAssignment))  # type: ignore[call-overload]
        session.exec(delete(VocabularyBookItem))  # type: ignore[call-overload]
        session.exec(delete(VocabularyBook))  # type: ignore[call-overload]
        session.exec(delete(VocabularyWord))  # type: ignore[call-overload]
        session.exec(delete(Attempt))  # type: ignore[call-overload]
        session.exec(delete(PracticeSession))  # type: ignore[call-overload]
        session.exec(delete(StudentBadge))  # type: ignore[call-overload]
        session.exec(delete(Student))  # type: ignore[call-overload]
        session.exec(delete(Classroom))  # type: ignore[call-overload]
        session.exec(delete(ScenarioQuestion))  # type: ignore[call-overload]
        session.exec(delete(Scenario))  # type: ignore[call-overload]
        session.exec(delete(RepeatSentence))  # type: ignore[call-overload]
        session.exec(delete(Passage))  # type: ignore[call-overload]
        session.exec(delete(WordlistEntry))  # type: ignore[call-overload]
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

    set_engine(None)
    engine.dispose()


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
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
