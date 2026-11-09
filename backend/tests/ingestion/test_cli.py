"""The manual ingestion CLI: argument validation and per-warehouse failure handling."""

from types import SimpleNamespace

import pytest

from smart_basket.config import Settings
from smart_basket.ingestion import IngestSetupError
from smart_basket.ingestion import __main__ as cli


def configure(monkeypatch, warehouses: str = "W1,W2") -> None:
    settings = Settings(_env_file=None, mercadona_warehouses=warehouses, ingest_delay_seconds=0)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "MercadonaAdapter", FakeAdapter)


class FakeAdapter:
    def __init__(self, *, delay: float) -> None:
        self.delay = delay

    def close(self) -> None:
        pass


def test_negative_max_categories_is_rejected(monkeypatch):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["mercadona", "--max-categories", "-1"])

    assert exit_info.value.code == 2


def test_setup_error_prints_one_line_and_exits_with_code_two(monkeypatch, capsys):
    configure(monkeypatch, "W1")

    def fake_ingest(adapter, warehouse, *, data_dir, max_categories=None):
        raise IngestSetupError("chain 'mercadona' not found; run `smart-basket-seed` first")

    monkeypatch.setattr(cli, "ingest_catalog", fake_ingest)

    assert cli.main(["mercadona"]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == (
        "error: chain 'mercadona' not found; run `smart-basket-seed` first"
    )


def test_a_failing_warehouse_does_not_stop_the_next(monkeypatch):
    configure(monkeypatch)
    calls = []

    def fake_ingest(adapter, warehouse, *, data_dir, max_categories=None):
        calls.append(warehouse)
        if warehouse == "W1":
            raise RuntimeError("boom")
        return SimpleNamespace(
            run_id=2,
            chain_code="mercadona",
            zone_code=warehouse,
            status="succeeded",
            products_seen=1,
            prices_changed=0,
            errors=(),
        )

    monkeypatch.setattr(cli, "ingest_catalog", fake_ingest)

    assert cli.main(["mercadona"]) == 1
    assert calls == ["W1", "W2"]
