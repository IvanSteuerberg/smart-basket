"""The manual ingestion CLI: argument validation, the adapter registry and per-zone failures."""

from types import SimpleNamespace

import pytest

from smart_basket.config import Settings
from smart_basket.ingestion import ImageBackfillSummary, IngestSetupError
from smart_basket.ingestion import __main__ as cli
from smart_basket.ingestion.__main__ import ChainEntry


class FakeAdapter:
    """A chain adapter that never touches the network."""

    def __init__(self, *, delay: float) -> None:
        self.delay = delay

    def crawl(self, zone_code, *, max_categories=None):
        return iter(())

    def close(self) -> None:
        pass


def configure(
    monkeypatch,
    warehouses: str = "W1,W2",
    *,
    chains: tuple[str, ...] = ("mercadona",),
) -> None:
    """Replace the registry with fake chains and the settings with fake zones."""
    settings = Settings(
        _env_file=None,
        mercadona_warehouses=warehouses,
        dia_zones="24001",
        ingest_delay_seconds=0,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    entries = {
        "mercadona": ChainEntry(FakeAdapter, zones=lambda s: s.mercadona_warehouse_codes),
    }
    if "dia" in chains:
        entries["dia"] = ChainEntry(FakeAdapter, zones=lambda s: s.dia_zone_codes)
    monkeypatch.setattr(cli, "ADAPTERS", entries)


def record_ingest(monkeypatch) -> list[str]:
    """Patch the store with a recorder and return the zones it was called with, in order."""
    calls: list[str] = []

    def fake_ingest(adapter, zone, *, data_dir, max_categories=None):
        calls.append(zone)
        return SimpleNamespace(
            run_id=1,
            chain_code="mercadona",
            zone_code=zone,
            status="succeeded",
            products_seen=1,
            prices_changed=0,
            errors=(),
        )

    monkeypatch.setattr(cli, "ingest_catalog", fake_ingest)
    return calls


def test_negative_max_categories_is_rejected(monkeypatch):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["mercadona", "--max-categories", "-1"])

    assert exit_info.value.code == 2


@pytest.mark.parametrize("conflict", [["--max-categories", "2"], ["--dry-run"]])
def test_backfill_images_is_exclusive_with_the_crawl_modes(monkeypatch, conflict):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["mercadona", "--backfill-images", *conflict])

    assert exit_info.value.code == 2


def test_backfill_images_prints_the_summary_without_creating_an_adapter(monkeypatch, capsys):
    calls = []

    def fake_backfill(chain, *, data_dir):
        calls.append((chain, data_dir))
        return ImageBackfillSummary(updated=3, unchanged=1, missing=0, responses_skipped=0)

    def no_adapter(**kwargs):
        raise AssertionError("the backfill must not build a network adapter")

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, data_dir="data"))
    monkeypatch.setattr(cli, "backfill_images", fake_backfill)
    monkeypatch.setattr(cli, "ADAPTERS", {"mercadona": ChainEntry(no_adapter, lambda s: [])})

    assert cli.main(["mercadona", "--backfill-images"]) == 0
    assert calls[0][0] == "mercadona"
    assert capsys.readouterr().out.strip() == "images: 3 updated, 1 unchanged, 0 without image"


def test_setup_error_prints_one_line_and_exits_with_code_two(monkeypatch, capsys):
    configure(monkeypatch, "W1")

    def fake_ingest(adapter, zone, *, data_dir, max_categories=None):
        raise IngestSetupError("chain 'mercadona' not found; run `smart-basket-seed` first")

    monkeypatch.setattr(cli, "ingest_catalog", fake_ingest)

    assert cli.main(["mercadona"]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == (
        "error: chain 'mercadona' not found; run `smart-basket-seed` first"
    )


def test_a_failing_zone_does_not_stop_the_next(monkeypatch):
    configure(monkeypatch)
    calls = []

    def fake_ingest(adapter, zone, *, data_dir, max_categories=None):
        calls.append(zone)
        if zone == "W1":
            raise RuntimeError("boom")
        return SimpleNamespace(
            run_id=2,
            chain_code="mercadona",
            zone_code=zone,
            status="succeeded",
            products_seen=1,
            prices_changed=0,
            errors=(),
        )

    monkeypatch.setattr(cli, "ingest_catalog", fake_ingest)

    assert cli.main(["mercadona"]) == 1
    assert calls == ["W1", "W2"]


@pytest.mark.parametrize("flag", ["--zone", "--warehouse"])
def test_zone_and_warehouse_flags_are_aliases(monkeypatch, flag):
    configure(monkeypatch)
    calls = record_ingest(monkeypatch)

    assert cli.main(["mercadona", flag, "3683"]) == 0
    assert calls == ["3683"]


def test_chain_choices_and_zones_come_from_the_registry(monkeypatch):
    configure(monkeypatch, chains=("mercadona", "dia"))
    calls = record_ingest(monkeypatch)

    assert cli.main(["dia"]) == 0
    assert calls == ["24001"]

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["alcampo"])

    assert exit_info.value.code == 2


def test_dry_run_prints_each_zone_without_persisting(monkeypatch, capsys):
    configure(monkeypatch, "W1,W2")
    monkeypatch.setattr(
        cli, "ingest_catalog", lambda *args, **kwargs: pytest.fail("dry run must not persist")
    )

    assert cli.main(["mercadona", "--dry-run"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == [
        "W1: categories=0 products=0 responses=0 errors=0 status=succeeded complete=False",
        "W2: categories=0 products=0 responses=0 errors=0 status=succeeded complete=False",
    ]
