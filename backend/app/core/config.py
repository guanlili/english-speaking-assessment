import warnings
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    # 必填：若给默认随机值，环境变量丢失时不报错，多 worker 下各进程密钥不同，token 时好时坏
    SECRET_KEY: str
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    # 测试专用库（conftest 会拒绝它指向开发库）。默认挂在同一实例上，CI/本地零配置
    POSTGRES_DB_TEST: str = "app_test"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_TEST_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB_TEST,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    # ── 口语评测评分（PRD §7.2：引擎藏在可替换接口后面）──
    # mock=离线演示/测试；ark=火山方舟（需 ARK_API_KEY，模型名必须带日期后缀）
    SCORING_PROVIDER: Literal["mock", "ark"] = "mock"
    ARK_API_KEY: str | None = None
    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    # 方舟 API 调用名必须用带日期后缀的快照名，广场短名（doubao-seed-2-0-lite）会 404
    ARK_ASR_MODEL: str = "doubao-seed-2-0-lite-260428"
    # 开放题 rubric 评分模型（同一模型走 chat 接口；豆包或 DeepSeek 系列均可）
    ARK_RUBRIC_MODEL: str = "doubao-seed-2-0-lite-260428"
    # 标准音合成：方舟域名没有 /audio/speech，走 vei AI 网关的 OpenAI 兼容接口；
    # 网关密钥与方舟 Key 是两套（console.volcengine.com/vei/aigateway 创建），
    # 未配置时 TTS 返回 503，上传现成音频的通道不受影响
    ARK_TTS_BASE_URL: str = "https://ai-gateway.vei.volces.com/v1"
    ARK_TTS_API_KEY: str | None = None
    ARK_TTS_MODEL: str = "doubao-tts"
    # 音色从控制台「音色列表」选择后填写（bigtts 系命名），留空则生成时报 503
    ARK_TTS_VOICE: str = ""
    # 后台评分线程数（PRD：8 个 worker 可在 2 分钟内打完 40 人）
    SCORING_WORKERS: int = 2
    # 音频落盘目录（compose 里挂卷到 /app/audio）
    AUDIO_STORAGE_DIR: str = "./audio"
    MAX_AUDIO_MB: int = 20
    # 练习日切分时区（教室在国内；UTC 会在早八点切日）
    PRACTICE_TZ: str = "Asia/Shanghai"
    # 是否开放自助注册。代码默认关（安全兜底）；本地 .env.example 开着便于开发演示，
    # 生产由 GitHub Secrets 控制（deploy.yml 默认写 false）
    USERS_OPEN_REGISTRATION: bool = False

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
