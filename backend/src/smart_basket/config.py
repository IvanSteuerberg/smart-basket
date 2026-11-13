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

    overpass_url: str = "https://overpass-api.de/api/interpreter"
    stores_bbox: str = "42.56,-5.62,42.63,-5.52"
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    #: Stores looked at per recommendation, and how far the shopper is willing to go.
    candidate_stores: int = 10
    walk_radius_m: int = 3000
    car_radius_m: int = 20000

    data_dir: Path = Path("data")
    mercadona_warehouses: str = "3683"
    ingest_delay_seconds: float = 1.5

    @property
    def mercadona_warehouse_codes(self) -> list[str]:
        """The configured warehouse codes, without blanks left by the comma list."""
        return [code.strip() for code in self.mercadona_warehouses.split(",") if code.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings singleton; tests can call `get_settings.cache_clear()` after changing the env."""
    return Settings()
