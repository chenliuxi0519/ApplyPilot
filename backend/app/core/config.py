import secrets
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

# AES 允许的密钥长度，与官方 EncryptedSerializer 的校验一致。
AES_KEY_SIZES = (16, 24, 32)


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)

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

    AGENT_BASE_URL: str | None = None
    AGENT_API_KEY: str | None = None
    AGENT_MODEL: str = "deepseek-v4-flash"

    # 新建运行用哪个引擎。恢复永远按运行自己记下的引擎走，不看这个开关，
    # 所以切回 loop 之后，已经暂停的 graph 运行仍然能被批准。
    AGENT_ENGINE: Literal["loop", "graph"] = "loop"

    def missing_agent_settings(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in ("AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL")
            if not getattr(self, name)
        )

    @property
    def agent_is_configured(self) -> bool:
        return not self.missing_agent_settings()

    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

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
    def CHECKPOINT_DATABASE_URI(self) -> str:
        """LangGraph checkpointer 用的连接串。

        它直接走 psycopg，不认 SQLAlchemy 的 ``+psycopg`` 方言后缀，
        所以在这里换掉 scheme，而不是改 SQLALCHEMY_DATABASE_URI——
        后者被 alembic 和 core.db 依赖着。
        """
        return str(self.SQLALCHEMY_DATABASE_URI).replace(
            "postgresql+psycopg://", "postgresql://", 1
        )

    # checkpoint 里会存下完整对话与工具结果，因此与 SECRET_KEY 分开管理：
    # 两者轮换周期不同，泄露面也不同。必须是 16/24/32 字节。
    CHECKPOINT_ENCRYPTION_KEY: str | None = None

    @property
    def checkpoint_is_configured(self) -> bool:
        return bool(self.CHECKPOINT_ENCRYPTION_KEY)

    @model_validator(mode="after")
    def _enforce_checkpoint_encryption(self) -> Self:
        """checkpoint 密钥的唯一判定点。

        local 之外的环境一律要求配好密钥：checkpoint 存的是完整对话，
        缺密钥必须在启动时就失败，而不是等到第一个 Graph 请求才发现。
        local 允许不配（此时不会有任何 checkpoint 被写入），但只要配了，
        长度就必须合法——不接受"配了一个用不了的值"这种中间状态。
        """
        key = self.CHECKPOINT_ENCRYPTION_KEY
        if not key:
            if self.ENVIRONMENT != "local":
                raise ValueError(
                    "CHECKPOINT_ENCRYPTION_KEY 未配置。checkpoint 会存下完整对话"
                    "与工具结果，必须加密；请配置 16、24 或 32 字节的密钥。"
                )
            return self

        size = len(key.encode("utf-8"))
        if size not in AES_KEY_SIZES:
            raise ValueError(
                f"CHECKPOINT_ENCRYPTION_KEY 必须是 16、24 或 32 字节，当前为 {size}。"
            )
        return self

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

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = f'{var_name} 仍使用默认值 "changethis"，请在部署前更换。'
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
