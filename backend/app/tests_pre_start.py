import logging

from sqlalchemy import Engine, create_engine
from sqlmodel import Session, select
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init(db_engine: Engine) -> None:
    try:
        # 连接的是管理库 postgres：测试库本身由 conftest 按需创建，这里只等实例可达
        with Session(db_engine) as session:
            session.exec(select(1))
    except Exception as e:
        logger.error(e)
        raise e


def main() -> None:
    logger.info("Initializing service")
    # 测试连接测试库所在实例（与主库同 host），连 postgres 管理库；
    # 测试库绝不能指向应用库，conftest 会再校验一次，这里提前失败给出更清晰的错误
    if str(settings.SQLALCHEMY_DATABASE_TEST_URI) == str(
        settings.SQLALCHEMY_DATABASE_URI
    ):
        raise RuntimeError(
            f"POSTGRES_DB_TEST ({settings.POSTGRES_DB_TEST}) must not equal "
            f"POSTGRES_DB ({settings.POSTGRES_DB}). Tests DELETE all rows."
        )
    admin_uri = (
        str(settings.SQLALCHEMY_DATABASE_TEST_URI).rsplit("/", 1)[0] + "/postgres"
    )
    init(create_engine(admin_uri))
    logger.info("Service finished initializing")


if __name__ == "__main__":
    main()
