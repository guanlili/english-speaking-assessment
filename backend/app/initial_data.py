import logging

from sqlalchemy import create_engine
from sqlmodel import Session

from app.core.db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init() -> None:
    # C4b：种子写 user/篇目/句型等表——admin 连接绕 RLS（受限角色无上下文
    # 写业务表会被默认拒绝策略拦死；种子固定归默认租户由迁移语义保证）
    from app.core.config import settings

    engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    with Session(engine) as session:
        init_db(session)
    engine.dispose()


def main() -> None:
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
