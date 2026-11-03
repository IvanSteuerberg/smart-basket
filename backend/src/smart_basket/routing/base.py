"""Engine-independent routing types. The optimizer only sees the resulting `TravelTimes`."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from smart_basket.optimizer.models import TravelTimes


class TravelMode(StrEnum):
    WALK = "walk"
    CAR = "car"


@dataclass(frozen=True, slots=True)
class GeoPoint:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class StoreLocation:
    store_id: int
    point: GeoPoint


class RoutingError(RuntimeError):
    """The routing engine failed or returned something unusable."""


class RoutingEngine(Protocol):
    """Anything that can produce a travel-time matrix (Valhalla now, OSRM to compare, 0009)."""

    def travel_times(
        self, origin: GeoPoint, stores: Sequence[StoreLocation], mode: TravelMode
    ) -> TravelTimes:
        """Minutes between the origin (index 0) and every store, in both directions."""
        ...
