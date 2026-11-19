"""The worker's catalog job and the ingestion settings, without network or database."""

import logging
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from smart_basket.config import Settings
from smart_basket.ingestion.__main__ import ChainEntry
from smart_basket.llm.base import LLMError
from smart_basket.worker import jobs


class _Adapter:
    """A chain adapter that never touches the network."""

    def __init__(self, *, delay: float) -> None:
        self.delay = delay

    def close(self) -> None:
        pass


def _patch_ingestion(
    monkeypatch,
    *,
    warehouses: str = "W1, W2",
    dia_zones: str = "24001",
    chains: tuple[str, ...] = ("mercadona",),
    failing: tuple[str, ...] = (),
) -> list[str]:
    """Point the job at fake chains and zones and return the zones it tried, in order."""
    settings = Settings(
        _env_file=None,
        mercadona_warehouses=warehouses,
        dia_zones=dia_zones,
        ingest_delay_seconds=0,
    )
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    entries = {
        "mercadona": ChainEntry(_Adapter, zones=lambda s: s.mercadona_warehouse_codes),
    }
    if "dia" in chains:
        entries["dia"] = ChainEntry(_Adapter, zones=lambda s: s.dia_zone_codes)
    monkeypatch.setattr(jobs, "ADAPTERS", entries)
    calls: list[str] = []

    def fake_ingest(adapter, zone, *, data_dir):
        calls.append(zone)
        if zone in failing:
            raise RuntimeError("boom")
        return SimpleNamespace(
            run_id=1,
            chain_code="fake",
            zone_code=zone,
            status="succeeded",
            products_seen=2,
            prices_changed=0,
            errors=(),
        )

    monkeypatch.setattr(jobs, "ingest_catalog", fake_ingest)
    return calls


def test_ingestion_settings_defaults(monkeypatch):
    for variable in ("DATA_DIR", "MERCADONA_WAREHOUSES", "DIA_ZONES", "INGEST_DELAY_SECONDS"):
        monkeypatch.delenv(variable, raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_dir == Path("data")
    assert settings.mercadona_warehouses == "3683"
    assert settings.dia_zones == "24001"
    assert settings.ingest_delay_seconds == 1.5


def test_warehouse_codes_are_split_and_stripped():
    settings = Settings(_env_file=None, mercadona_warehouses=" W1, ,W2 ")
    assert settings.mercadona_warehouse_codes == ["W1", "W2"]


def test_dia_zone_codes_are_split_and_stripped():
    settings = Settings(_env_file=None, dia_zones=" 24001, ,24002 ")
    assert settings.dia_zone_codes == ["24001", "24002"]


def test_ingest_catalogs_swallows_a_failing_zone(monkeypatch):
    calls = _patch_ingestion(monkeypatch, failing=("W1",))
    monkeypatch.setattr(jobs, "match_products", lambda: None)

    jobs.ingest_catalogs()

    assert calls == ["W1", "W2"]


def test_every_registered_chain_ingests_its_configured_zones(monkeypatch):
    calls = _patch_ingestion(monkeypatch, chains=("mercadona", "dia"))
    monkeypatch.setattr(jobs, "match_products", lambda: None)

    jobs.ingest_catalogs()

    assert calls == ["W1", "W2", "24001"]


def test_a_failing_chain_does_not_stop_the_next(monkeypatch):
    calls = _patch_ingestion(monkeypatch, chains=("mercadona", "dia"), failing=("W1", "W2"))
    monkeypatch.setattr(jobs, "match_products", lambda: None)

    jobs.ingest_catalogs()

    assert calls == ["W1", "W2", "24001"]


def test_the_classifier_runs_once_after_every_chain_and_zone(monkeypatch):
    _patch_ingestion(monkeypatch, warehouses="W1, W2, W3", chains=("mercadona", "dia"))
    classified = []
    monkeypatch.setattr(jobs, "match_products", lambda: classified.append(True))

    jobs.ingest_catalogs()

    assert classified == [True]


def test_the_classifier_does_not_run_without_a_successful_ingestion(monkeypatch):
    _patch_ingestion(monkeypatch, failing=("W1", "W2"))
    classified = []
    monkeypatch.setattr(jobs, "match_products", lambda: classified.append(True))

    jobs.ingest_catalogs()

    assert classified == []


def test_a_classifier_error_is_logged_as_a_classification_error(monkeypatch, caplog):
    _patch_ingestion(monkeypatch)

    def fail() -> None:
        raise RuntimeError("classification boom")

    monkeypatch.setattr(jobs, "match_products", fail)
    with caplog.at_level(logging.ERROR, logger=jobs.log.name):
        jobs.ingest_catalogs()

    messages = [record.getMessage() for record in caplog.records]
    assert "product classification failed" in messages
    assert not any(message.startswith("catalog ingestion failed") for message in messages)


def test_the_catalog_agent_runs_after_the_classifier(monkeypatch):
    _patch_ingestion(monkeypatch)
    calls = []
    monkeypatch.setattr(jobs, "match_products", lambda: calls.append("match"))
    monkeypatch.setattr(jobs, "_run_catalog_agent_step", lambda settings: calls.append("agent"))

    jobs.ingest_catalogs()

    assert calls == ["match", "agent"]


def test_the_catalog_agent_does_not_run_without_a_successful_ingestion(monkeypatch):
    _patch_ingestion(monkeypatch, failing=("W1", "W2"))
    calls = []
    monkeypatch.setattr(jobs, "match_products", lambda: None)
    monkeypatch.setattr(jobs, "_run_catalog_agent_step", lambda settings: calls.append("agent"))

    jobs.ingest_catalogs()

    assert calls == []


def test_the_catalog_agent_step_embeds_and_runs(monkeypatch):
    settings = Settings(_env_file=None)
    provider = object()
    events = []
    monkeypatch.setattr(jobs, "embedding_provider_from_settings", lambda s: provider)
    monkeypatch.setattr(jobs, "session_scope", lambda: nullcontext(object()))
    monkeypatch.setattr(
        jobs,
        "embed_missing_canonicals",
        lambda session, p: events.append(("canonicals", p)) or 1,
    )
    monkeypatch.setattr(
        jobs,
        "embed_missing_products",
        lambda session, p: events.append(("products", p)) or 2,
    )
    monkeypatch.setattr(
        jobs,
        "run_catalog_agent",
        lambda session: events.append(("agent", session)) or {"assigned": 0},
    )

    jobs._run_catalog_agent_step(settings)

    assert events[0] == ("canonicals", provider)
    assert events[1] == ("products", provider)
    assert events[2][0] == "agent"


def test_the_catalog_agent_step_survives_a_provider_error(monkeypatch, caplog):
    settings = Settings(_env_file=None)

    def fail(settings):
        raise LLMError("EMBEDDING_PROVIDER=gemini needs GEMINI_API_KEY")

    monkeypatch.setattr(jobs, "embedding_provider_from_settings", fail)
    with caplog.at_level(logging.WARNING, logger=jobs.log.name):
        jobs._run_catalog_agent_step(settings)

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("catalog agent step skipped") for message in messages)
