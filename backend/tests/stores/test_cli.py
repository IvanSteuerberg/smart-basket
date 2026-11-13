"""The manual stores CLI: dry run, per-chain counts and exit codes, without network or database."""

import httpx

from smart_basket.config import Settings
from smart_basket.stores import OverpassClient, StoreSetupError
from smart_basket.stores import __main__ as cli


def element(osm_id: int, brand: str) -> dict:
    return {
        "type": "node",
        "id": osm_id,
        "lat": 42.6,
        "lon": -5.57,
        "tags": {"shop": "supermarket", "brand": brand},
    }


def configure(monkeypatch, handler, *, bbox: str = "42.56,-5.62,42.63,-5.52") -> None:
    settings = Settings(
        _env_file=None,
        overpass_url="https://overpass.test/api",
        stores_bbox=bbox,
        database_url="postgresql+psycopg://nobody@127.0.0.1:1/none",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def factory(*, url: str) -> OverpassClient:
        return OverpassClient(httpx.Client(transport=httpx.MockTransport(handler)), url=url)

    monkeypatch.setattr(cli, "OverpassClient", factory)


def test_a_dry_run_prints_the_counts_and_touches_no_database(monkeypatch, capsys):
    elements = [element(1, "Mercadona"), element(2, "Lidl"), element(3, "Eroski")]
    configure(monkeypatch, lambda request: httpx.Response(200, json={"elements": elements}))

    assert cli.main(["import", "--dry-run"]) == 0
    assert capsys.readouterr().out.splitlines() == ["mercadona: 1", "lidl: 1"]


def test_an_overpass_failure_exits_with_code_one(monkeypatch, capsys):
    configure(monkeypatch, lambda request: httpx.Response(500))

    assert cli.main(["import"]) == 1
    assert "HTTP 500" in capsys.readouterr().err


def test_a_setup_error_exits_with_code_two(monkeypatch, capsys):
    configure(monkeypatch, lambda request: httpx.Response(200, json={"elements": []}))

    def fail(observations, bbox):
        raise StoreSetupError("chain 'mercadona' not found; run `smart-basket-seed` first")

    monkeypatch.setattr(cli, "import_stores", fail)

    assert cli.main(["import"]) == 2
    assert capsys.readouterr().err.strip() == (
        "error: chain 'mercadona' not found; run `smart-basket-seed` first"
    )


def test_a_malformed_bbox_exits_with_code_one(monkeypatch, capsys):
    configure(monkeypatch, lambda request: httpx.Response(200), bbox="42.56")

    assert cli.main(["import", "--dry-run"]) == 1
    assert "four numbers" in capsys.readouterr().err
