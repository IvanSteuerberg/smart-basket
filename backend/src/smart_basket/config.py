"""Application settings, read from environment variables (and an optional `.env` file)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field maps to an upper-case environment variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://smart_basket:smart_basket@localhost:5432/smart_basket",
        description="SQLAlchemy URL of the application database.",
    )
    log_level: str = "INFO"
    timezone: str = "Europe/Madrid"

    llm_provider: Literal["ollama", "gemini", "none"] = "ollama"
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3.5:0.8b"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: float = 30.0

    valhalla_url: str = "http://routing:8002"
    routing_timeout_seconds: float = 10.0

    data_dir: Path = Path("data")
    mercadona_warehouses: str = "3683"
    ingest_delay_seconds: float = 1.5


@lru_cache
def get_settings() -> Settings:
    """Settings singleton; tests can call `get_settings.cache_clear()` after changing the env."""
    return Settings()
