from smart_basket.config import Settings
from smart_basket.worker.__main__ import build_scheduler


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("LLM_PROVIDER", "none")
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith("@h:5432/d")
    assert settings.llm_provider == "none"
    assert Settings(_env_file=None).ollama_url  # has a default


def test_ollama_default_is_the_host_from_docker(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    assert Settings(_env_file=None).ollama_url == "http://host.docker.internal:11434"


def test_worker_schedules_the_placeholder_jobs():
    ids = {job.id for job in build_scheduler().get_jobs()}
    assert ids == {
        "ingest_catalogs",
        "match_products",
        "refresh_bi",
        "ensure_price_history_partitions",
        "import_stores",
    }
