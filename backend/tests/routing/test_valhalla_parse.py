"""Valhalla client against a fake transport: request shape and response parsing only.

The real engine is not exercised in unit tests (it needs the routing service and map data).
"""

import json
from decimal import Decimal as D

import httpx
import pytest

from smart_basket.routing import GeoPoint, RoutingError, StoreLocation, TravelMode, ValhallaClient

ORIGIN = GeoPoint(42.5987, -5.5671)
STORES = [StoreLocation(7, GeoPoint(42.60, -5.57)), StoreLocation(9, GeoPoint(42.59, -5.56))]


def client(handler) -> ValhallaClient:
    return ValhallaClient(
        "http://routing:8002",
        client=httpx.Client(base_url="http://routing:8002", transport=httpx.MockTransport(handler)),
    )


def test_matrix_request_and_minutes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        n = len(seen["body"]["sources"])
        rows = [
            [
                {
                    "from_index": i,
                    "to_index": j,
                    "time": None if (i, j) == (2, 1) else 90 * j,
                    "distance": 1.0,
                }
                for j in range(n)
            ]
            for i in range(n)
        ]
        return httpx.Response(200, json={"sources_to_targets": rows})

    times = client(handler).travel_times(ORIGIN, STORES, TravelMode.WALK)
    assert seen["path"] == "/sources_to_targets"
    assert seen["body"]["costing"] == "pedestrian"
    assert seen["body"]["sources"][0] == {"lat": 42.5987, "lon": -5.5671}
    assert times.store_ids == (7, 9)
    assert times.minutes[0][1] == D("1.50")
    assert times.minutes[0][2] == D("3.00")
    assert times.minutes[1][1] == D(0)
    assert times.minutes[2][1] is None


def test_car_uses_auto_costing():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["costing"] == "auto"
        rows = [[{"from_index": i, "to_index": j, "time": 60} for j in range(3)] for i in range(3)]
        return httpx.Response(200, json={"sources_to_targets": rows})

    client(handler).travel_times(ORIGIN, STORES, TravelMode.CAR)


def test_errors_become_routing_errors():
    with pytest.raises(RoutingError):
        client(lambda r: httpx.Response(500, text="boom")).travel_times(
            ORIGIN, STORES, TravelMode.WALK
        )
    with pytest.raises(RoutingError):
        client(lambda r: httpx.Response(200, json={})).travel_times(ORIGIN, STORES, TravelMode.WALK)
