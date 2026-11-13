"""Valhalla client for the `/sources_to_targets` matrix API (decision 0009).

Not exercised by unit tests: it needs the `routing` service with the León extract.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from smart_basket.optimizer.models import TravelTimes
from smart_basket.routing.base import GeoPoint, RoutingError, StoreLocation, TravelMode

COSTING = {TravelMode.WALK: "pedestrian", TravelMode.CAR: "auto"}
MINUTE_STEP = Decimal("0.01")
#: Valhalla encodes its route shapes with six decimals of precision.
SHAPE_PRECISION = 6


def decode_polyline(encoded: str, precision: int = SHAPE_PRECISION) -> list[tuple[float, float]]:
    """Decode an encoded polyline into `[lat, lon]` pairs (latitude first, as Valhalla)."""
    factor = 10**precision
    coordinates: list[tuple[float, float]] = []
    index = 0
    lat = lon = 0
    while index < len(encoded):
        for axis in ("lat", "lon"):
            value = shift = 0
            while True:
                if index >= len(encoded):
                    raise RoutingError("unexpected valhalla response: truncated polyline")
                chunk = ord(encoded[index]) - 63
                index += 1
                value |= (chunk & 0x1F) << shift
                shift += 5
                if chunk < 0x20:
                    break
            delta = ~(value >> 1) if value & 1 else value >> 1
            if axis == "lat":
                lat += delta
            else:
                lon += delta
        coordinates.append((lat / factor, lon / factor))
    return coordinates


class ValhallaClient:
    def __init__(
        self, base_url: str, timeout: float = 10.0, client: httpx.Client | None = None
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def travel_times(
        self, origin: GeoPoint, stores: Sequence[StoreLocation], mode: TravelMode
    ) -> TravelTimes:
        nodes = [origin, *(s.point for s in stores)]
        locations = [{"lat": p.latitude, "lon": p.longitude} for p in nodes]
        body = {
            "sources": locations,
            "targets": locations,
            "costing": COSTING[mode],
            "units": "kilometers",
            "verbose": True,
        }
        try:
            response = self._client.post("/sources_to_targets", json=body)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f"valhalla matrix request failed: {exc}") from exc
        return TravelTimes(
            store_ids=tuple(s.store_id for s in stores),
            minutes=self._parse(data, len(nodes)),
        )

    def route_shape(
        self, points: Sequence[GeoPoint], mode: TravelMode
    ) -> list[tuple[float, float]]:
        """Route through `points` in order, as `[lat, lon]` pairs of every leg's shape."""
        body = {
            "locations": [{"lat": p.latitude, "lon": p.longitude} for p in points],
            "costing": COSTING[mode],
            "units": "kilometers",
        }
        try:
            response = self._client.post("/route", json=body)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f"valhalla route request failed: {exc}") from exc
        legs = (data.get("trip") or {}).get("legs")
        if not isinstance(legs, list) or not legs:
            raise RoutingError("unexpected valhalla response: no trip legs")
        shape: list[tuple[float, float]] = []
        for leg in legs:
            encoded = leg.get("shape") if isinstance(leg, dict) else None
            if not isinstance(encoded, str):
                raise RoutingError("unexpected valhalla response: leg without shape")
            shape.extend(decode_polyline(encoded))
        if len(shape) < 2:
            raise RoutingError("unexpected valhalla response: route shape too short")
        return shape

    @staticmethod
    def _parse(data: dict[str, Any], n: int) -> tuple[tuple[Decimal | None, ...], ...]:
        rows = data.get("sources_to_targets")
        if not isinstance(rows, list) or len(rows) != n:
            raise RoutingError("unexpected valhalla response: no sources_to_targets matrix")
        matrix: list[list[Decimal | None]] = [[None] * n for _ in range(n)]
        for row in rows:
            for cell in row:
                i, j = cell.get("from_index"), cell.get("to_index")
                seconds = cell.get("time")
                if i is None or j is None:
                    raise RoutingError("unexpected valhalla response: cell without indices")
                if i == j:
                    matrix[i][j] = Decimal(0)
                elif seconds is not None:
                    minutes = Decimal(str(seconds)) / 60
                    matrix[i][j] = minutes.quantize(MINUTE_STEP, rounding=ROUND_HALF_UP)
        return tuple(tuple(r) for r in matrix)
