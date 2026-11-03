from fastapi.testclient import TestClient

from smart_basket.api import app as app_module
from smart_basket.api import health
from smart_basket.api.app import create_app


def client(monkeypatch, db_ok: bool) -> TestClient:
    monkeypatch.setattr(health, "check_database", lambda: db_ok)
    return TestClient(create_app())


def test_health_ok(monkeypatch):
    response = client(monkeypatch, True).get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_reports_database_down(monkeypatch):
    response = client(monkeypatch, False).get("/api/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_openapi_is_served_under_api(monkeypatch):
    assert client(monkeypatch, True).get("/api/openapi.json").status_code == 200
    assert app_module.app.title == "Smart Basket API"
