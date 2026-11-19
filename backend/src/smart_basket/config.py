"""Application settings, read from environment variables (and an optional `.env` file)."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
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

    #: Recommender agent (ADR 0022): `default` is the deterministic degradation mode.
    agent_policy: str = "default"
    agent_model: str | None = None
    agent_low_confidence_threshold: float | None = 0.6
    agent_max_steps: int = 6
    agent_time_budget_ms: int = 10_000
    agent_fewshot: bool = False

    #: Embeddings for public catalog text (ADR 0022).
    embedding_provider: str = "gemini"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768

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
    match_decisions_file: Path | None = None
    mercadona_warehouses: str = "3683"
    dia_zones: str = "24001"
    ingest_delay_seconds: float = 1.5

    @field_validator("match_decisions_file", mode="before")
    @classmethod
    def _empty_as_none(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return Path(v) if isinstance(v, str) else v

    def resolve_match_decisions_file(self) -> Path | None:
        """Resolve `match_decisions_file` and enforce that it stays within `data_dir`."""
        if self.match_decisions_file is None:
            return None
        data_root = self.data_dir.resolve()
        candidate = self.match_decisions_file
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved_cwd = candidate.resolve()
            resolved_data = (data_root / candidate).resolve()
            if resolved_cwd.is_relative_to(data_root):
                resolved = resolved_cwd
            elif resolved_data.is_relative_to(data_root):
                resolved = resolved_data
            else:
                resolved = resolved_cwd

        if not resolved.is_relative_to(data_root):
            raise ValueError(
                f"MATCH_DECISIONS_FILE ({self.match_decisions_file}) must be inside "
                f"DATA_DIR ({self.data_dir})"
            )
        return resolved

    @property
    def mercadona_warehouse_codes(self) -> list[str]:
        """The configured warehouse codes, without blanks left by the comma list."""
        return [code.strip() for code in self.mercadona_warehouses.split(",") if code.strip()]

    @property
    def dia_zone_codes(self) -> list[str]:
        """The configured Dia postal codes, without blanks left by the comma list."""
        return [code.strip() for code in self.dia_zones.split(",") if code.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings singleton; tests can call `get_settings.cache_clear()` after changing the env."""
    return Settings()
