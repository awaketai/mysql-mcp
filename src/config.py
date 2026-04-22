"""Application configuration via environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class MySQLConfig(BaseSettings):
    """MySQL connection and pool settings."""

    host: str = Field(default="localhost", alias="MYSQL_HOST")
    port: int = Field(default=3306, alias="MYSQL_PORT")
    user: str = Field(alias="MYSQL_USER")
    password: str = Field(alias="MYSQL_PASSWORD")
    charset: str = Field(default="utf8mb4", alias="MYSQL_CHARSET")
    ssl: bool = Field(default=False, alias="MYSQL_SSL")

    pool_min_size: int = Field(default=2, alias="MYSQL_POOL_MIN_SIZE")
    pool_max_size: int = Field(default=10, alias="MYSQL_POOL_MAX_SIZE")
    pool_recycle: int = Field(default=3600, alias="MYSQL_POOL_RECYCLE")

    model_config = {"env_prefix": "", "populate_by_name": True}


class OpenAIConfig(BaseSettings):
    """OpenAI API settings."""

    api_key: str = Field(alias="OPENAI_API_KEY")
    model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    max_retries: int = Field(default=3, alias="OPENAI_MAX_RETRIES")
    timeout: int = Field(default=60, alias="OPENAI_TIMEOUT")

    model_config = {"env_prefix": "", "populate_by_name": True}


class AppConfig(BaseSettings):
    """Top-level application settings aggregating all sub-configs."""

    mysql: MySQLConfig = Field(default_factory=MySQLConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)

    allowed_databases: list[str] = Field(default_factory=list, alias="ALLOWED_DATABASES")
    default_database: str | None = Field(default=None, alias="DEFAULT_DATABASE")
    schema_refresh_interval: int = Field(default=0, alias="SCHEMA_REFRESH_INTERVAL")
    query_timeout: int = Field(default=30, alias="QUERY_TIMEOUT")
    max_limit: int = Field(default=1000, alias="MAX_LIMIT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = {"env_prefix": "", "populate_by_name": True}
