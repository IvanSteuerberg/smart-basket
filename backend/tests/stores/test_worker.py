"""The monthly store job and the settings it reads, without network or database."""

from types import SimpleNamespace

from smart_basket.config import Settings
from smart_basket.worker import __main__ as worker
from smart_basket.worker import jobs


def settings(**overrides) -> Settings:
    values = {
        "overpass_url": "https://overpass.test/api",
        "stores_bbox": "42.56,-5.62,42.63,-5.52",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_store_settings_defaults(monkeypatch):
    for variable in ("OVERPASS_URL", "STORES_BBOX"):
        monkeypatch.delenv(variable, raising=False)
    defaults = Settings(_env_file=None)

    assert defaults.overpass_url == "https://overpass-api.de/api/interpreter"
    assert defaults.stores_bbox == "42.56,-5.62,42.63,-5.52"


def test_the_job_runs_monthly_on_the_first_at_0417():
    job = next(job for job in worker.build_scheduler().get_jobs() if job.id == "import_stores")

    assert str(job.trigger) == "cron[day='1', hour='4', minute='17']"


def test_the_job_fetches_and_imports_the_stores(monkeypatch):
    calls = []

    class Client:
        def __init__(self, *, url: str) -> None:
            calls.append(("client", url))

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *exc: object) -> None:
            pass

    summary = SimpleNamespace(
        per_chain={"lidl": 1}, run_ids=(1,), inserted=1, updated=0, deactivated=0
    )
    monkeypatch.setattr(jobs, "get_settings", lambda: settings())
    monkeypatch.setattr(jobs.stores, "OverpassClient", Client)
    monkeypatch.setattr(jobs.stores, "fetch_stores", lambda client, bbox: ("observations",))
    monkeypatch.setattr(jobs.stores, "import_stores", lambda observations, bbox: summary)
    monkeypatch.setattr(
        jobs.stores, "log_store_summary", lambda value: calls.append(("log", value))
    )

    jobs.import_stores()

    assert calls == [("client", "https://overpass.test/api"), ("log", summary)]


def test_a_failing_import_is_logged_and_swallowed(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("overpass down")

    monkeypatch.setattr(jobs, "get_settings", lambda: settings())
    monkeypatch.setattr(jobs.stores, "OverpassClient", boom)
    caplog.set_level("ERROR", logger="smart_basket.worker")

    jobs.import_stores()

    assert "store import failed" in caplog.text
    assert "overpass down" in caplog.text
