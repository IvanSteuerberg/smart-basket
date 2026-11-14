"""Geocoding through Nominatim with a mock transport (no network)."""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from smart_basket.api.app import create_app
from smart_basket.api.catalog import get_geocoder
from smart_basket.geo.nominatim import NominatimGeocoder, RateLimiter
from tests.api.conftest import FakeClock

DETAIL = "No se ha podido buscar la dirección. Prueba a marcar el punto en el mapa."


def geocoder_with(handler, clock: FakeClock) -> NominatimGeocoder:
    return NominatimGeocoder(
        "https://nominatim.test/search",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
        limiter=RateLimiter(interval=1.0, clock=clock, sleep=clock.sleep),
    )


def api_with(geocoder: NominatimGeocoder) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_geocoder] = lambda: geocoder
    return TestClient(app)


def test_places_are_returned_with_their_coordinates():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[
                {"display_name": "Calle Ancha, León", "lat": "42.5987", "lon": "-5.5671"},
                {"display_name": "Plaza Mayor, León", "lat": "42.5984", "lon": "-5.5665"},
            ],
        )

    client = api_with(geocoder_with(handler, FakeClock()))
    response = client.get("/api/geocode", params={"q": "calle ancha"})
    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {"label": "Calle Ancha, León", "lat": 42.5987, "lon": -5.5671},
            {"label": "Plaza Mayor, León", "lat": 42.5984, "lon": -5.5665},
        ]
    }

    params = requests[0].url.params
    assert params["q"] == "calle ancha"
    assert params["format"] == "jsonv2"
    assert params["limit"] == "5"
    assert params["countrycodes"] == "es"
    assert params["accept-language"] == "es"
    assert params["viewbox"] == "-5.62,42.63,-5.52,42.56"
    assert params["bounded"] == "1"
    assert requests[0].headers["User-Agent"].startswith("smart-basket/")


def test_at_most_five_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"display_name": f"Lugar {n}", "lat": "42.6", "lon": "-5.5"} for n in range(7)],
        )

    client = api_with(geocoder_with(handler, FakeClock()))
    assert len(client.get("/api/geocode", params={"q": "lugar"}).json()["results"]) == 5


def test_requests_are_limited_to_one_per_second():
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = api_with(geocoder_with(handler, clock))
    client.get("/api/geocode", params={"q": "calle uno"})
    client.get("/api/geocode", params={"q": "calle dos"})
    assert clock.now == 1.0

    client.get("/api/geocode", params={"q": "calle tres"})
    assert clock.now == 2.0


def test_repeated_queries_hit_the_cache():
    clock = FakeClock()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"display_name": "León", "lat": "42.6", "lon": "-5.5"}])

    client = api_with(geocoder_with(handler, clock))
    assert client.get("/api/geocode", params={"q": "León"}).json()["results"]
    assert client.get("/api/geocode", params={"q": "León"}).json()["results"]
    assert len(calls) == 1

    clock.now += 24 * 60 * 60 + 1
    client.get("/api/geocode", params={"q": "León"})
    assert len(calls) == 2


def test_the_cache_ignores_accents():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"display_name": "León", "lat": "42.6", "lon": "-5.5"}])

    client = api_with(geocoder_with(handler, FakeClock()))
    assert client.get("/api/geocode", params={"q": "León"}).json()["results"]
    assert client.get("/api/geocode", params={"q": "Leon"}).json()["results"]
    assert len(calls) == 1


def test_httpx_request_logs_are_silenced():
    # httpx logs every request URL at INFO, and those URLs carry the address.
    assert logging.getLogger("httpx").level == logging.WARNING


def test_nominatim_failure_is_a_503():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = api_with(geocoder_with(handler, FakeClock()))
    response = client.get("/api/geocode", params={"q": "calle ancha"})
    assert response.status_code == 503
    assert response.json() == {"detail": DETAIL}


def test_connection_errors_are_a_503():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    client = api_with(geocoder_with(handler, FakeClock()))
    response = client.get("/api/geocode", params={"q": "calle ancha"})
    assert response.status_code == 503
    assert response.json() == {"detail": DETAIL}


@pytest.mark.parametrize("query", ["", "   ", "ab", "  a  "])
def test_at_least_three_characters_once_stripped(query):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    client = api_with(geocoder_with(handler, FakeClock()))
    assert client.get("/api/geocode", params={"q": query}).status_code == 422
    assert calls == []
