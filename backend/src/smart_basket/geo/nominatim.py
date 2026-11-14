"""Nominatim geocoding for addresses in León.

The address only travels to Nominatim; it is never logged. Requests are limited to one per
second across the process and answers are cached in memory for a day (decision 0008).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from smart_basket import __version__
from smart_basket.preprocessor.text import fold

#: httpx logs every request URL at INFO, and those URLs carry the address.
logging.getLogger("httpx").setLevel(logging.WARNING)

USER_AGENT = f"smart-basket/{__version__}"
REQUEST_TIMEOUT_SECONDS = 10.0
MIN_INTERVAL_SECONDS = 1.0
CACHE_SIZE = 256
CACHE_TTL_SECONDS = 24 * 60 * 60.0
MAX_RESULTS = 5
#: Left, top, right, bottom of the León bounding box.
LEON_VIEWBOX = "-5.62,42.63,-5.52,42.56"


class GeocodingError(RuntimeError):
    """Nominatim could not answer; the API reports it as a 503."""


@dataclass(frozen=True, slots=True)
class Place:
    label: str
    lat: float
    lon: float


class RateLimiter:
    """At most one request per `interval` seconds across every caller of this instance."""

    def __init__(
        self,
        interval: float = MIN_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        """Block until the next request is allowed and reserve its slot."""
        with self._lock:
            now = self._clock()
            if self._last is not None and now - self._last < self.interval:
                self._sleep(self.interval - (now - self._last))
                now = self._clock()
            self._last = now


class _Cache:
    """A small LRU cache with a time to live, safe for concurrent readers and writers."""

    def __init__(
        self,
        size: int = CACHE_SIZE,
        ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.size = size
        self.ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, tuple[Place, ...]]] = OrderedDict()

    def get(self, key: str) -> tuple[Place, ...] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires, value = entry
            if self._clock() >= expires:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key: str, value: tuple[Place, ...]) -> None:
        with self._lock:
            self._entries[key] = (self._clock() + self.ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.size:
                self._entries.popitem(last=False)


class NominatimGeocoder:
    """Search addresses through Nominatim, limited to the bounding box of León."""

    def __init__(
        self,
        url: str,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.url = url
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self._cache = _Cache(clock=clock)
        self._limiter = limiter or RateLimiter(clock=clock)

    def search(self, query: str) -> tuple[Place, ...]:
        """Up to five places inside León, best first; raises `GeocodingError` on failure."""
        key = fold(" ".join(query.split()))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._limiter.wait()
        try:
            response = self._client.get(
                self.url,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": MAX_RESULTS,
                    "countrycodes": "es",
                    "accept-language": "es",
                    "viewbox": LEON_VIEWBOX,
                    "bounded": "1",
                },
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            places = tuple(_place(entry) for entry in response.json()[:MAX_RESULTS])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise GeocodingError("Nominatim did not answer") from exc
        self._cache.put(key, places)
        return places

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NominatimGeocoder:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _place(entry: dict[str, object]) -> Place:
    return Place(label=str(entry["display_name"]), lat=float(entry["lat"]), lon=float(entry["lon"]))
