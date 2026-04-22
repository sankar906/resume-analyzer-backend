"""Application settings (env / .env)."""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")

    postgres_server: str = Field(
        default="localhost",
        validation_alias=AliasChoices("POSTGRES_SERVER", "POSTGRES_HOST"),
    )
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_user: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="", validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(
        default="postgres",
        validation_alias=AliasChoices("POSTGRES_DB", "POSTGRES_DATABASE"),
    )

    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY")
    gemini_model: str = Field(
        default="gemini-3-flash-preview", validation_alias="GEMINI_MODEL"
    )
    gemini_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices("GEMINI_TEMPERATURE"),
        description="Sampling temperature for all Gemini generate_content calls (0 = deterministic).",
    )

    debug: bool = Field(default=False, validation_alias="DEBUG")

    db_pool_min: int = Field(default=5, validation_alias="DB_POOL_MIN")
    db_pool_max: int = Field(default=20, validation_alias="DB_POOL_MAX")

    @computed_field
    @property
    def asyncpg_dsn(self) -> str:
        if self.database_url:
            return self.database_url.strip()
        user = quote_plus(self.postgres_user)
        pwd = self.postgres_password
        auth = f"{user}:{quote_plus(pwd)}" if pwd else user
        return (
            f"postgresql://{auth}@{self.postgres_server}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def sqlalchemy_database_url(self) -> str:
        """Sync SQLAlchemy URL (psycopg2). Async URLs are rewritten for the sync engine."""
        if self.database_url:
            url = self.database_url.strip()
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://") :]
            if url.startswith("postgresql+asyncpg://"):
                url = "postgresql+psycopg2://" + url[len("postgresql+asyncpg://") :]
            elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
                url = "postgresql+psycopg2://" + url[len("postgresql://") :]
            return url
        user = quote_plus(self.postgres_user)
        pwd = self.postgres_password
        auth = f"{user}:{quote_plus(pwd)}" if pwd else user
        return (
            f"postgresql+psycopg2://{auth}@{self.postgres_server}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_gemini_environment() -> None:
    """Fail fast at startup if Gemini env is unusable (no network call)."""
    s = get_settings()
    if not (s.google_api_key or "").strip():
        raise RuntimeError(
            "GOOGLE_API_KEY is missing or empty. Set it in the environment for Gemini."
        )
    if not (s.gemini_model or "").strip():
        raise RuntimeError("GEMINI_MODEL is missing or empty.")
