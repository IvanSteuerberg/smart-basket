"""The worker's catalog job and the ingestion settings, without network or database."""

from pathlib import Path
from types import SimpleNamespace

from smart_basket.config import Settings
from smart_basket.worker import jobs


def test_ingestion_settings_defaults(monkeypatch):
    for variable in ("DATA_DIR", "MERCADONA_WAREHOUSES", "INGEST_DELAY_SECONDS"):
        monkeypatch.delenv(variable, raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_dir == Path("data")
    assert settings.mercadona_warehouses == "3683"
    assert settings.ingest_delay_seconds == 1.5


def test_ingest_catalogs_swallows_a_failing_warehouse(monkeypatch):
    settings = Settings(_env_file=None, mercadona_warehouses="W1, W2", ingest_delay_seconds=0)
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    calls = []

    class Adapter:
        def __init__(self, *, delay: float) -> None:
            self.delay = delay

        def close(self) -> None:
            pass

    monkeypatch.setattr(jobs, "MercadonaAdapter", Adapter)

    def fake_ingest(adapter, warehouse, *, data_dir):
        calls.append(warehouse)
        if warehouse == "W1":
            raise RuntimeError("boom")
        return SimpleNamespace(
            run_id=1,
            chain_code="mercadona",
            zone_code=warehouse,
            status="succeeded",
            products_seen=2,
            prices_changed=0,
            errors=(),
        )

    monkeypatch.setattr(jobs, "ingest_catalog", fake_ingest)
    jobs.ingest_catalogs()

    assert calls == ["W1", "W2"]
