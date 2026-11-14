"""Overpass answers, and the tags that decide which chain a supermarket belongs to.

Only the ten chains of the seed matter: every other brand is ignored, so a store of the database
is always a chain the recommender can price (decisions 0002, 0006).
"""

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_SECONDS = 90.0
OVERPASS_QUERY_TIMEOUT_SECONDS = 90

# Normalised OSM `brand` and `name` values (case, accents and punctuation stripped).
CHAIN_ALIASES: dict[str, str] = {
    "mercadona": "mercadona",
    "dia": "dia",
    "diago": "dia",
    "diamarket": "dia",
    "diamaxi": "dia",
    "maxidia": "dia",
    "laplazadedia": "dia",
    "alimerka": "alimerka",
    "lidl": "lidl",
    "alcampo": "alcampo",
    "alcamposupermercado": "alcampo",
    "mialcampo": "alcampo",
    "eleclerc": "eleclerc",
    "leclerc": "eleclerc",
    "lupa": "lupa",
    "carrefour": "carrefour",
    "carrefourexpress": "carrefour",
    "carrefourmarket": "carrefour",
    "gadis": "gadis",
    "claudio": "gadis",
    "aldi": "aldi",
}

# Brand variants that name a store format rather than another chain.
STORE_FORMATS: dict[str, str] = {
    "carrefourexpress": "Express",
    "carrefourmarket": "Market",
    "diago": "Dia&Go",
    "laplazadedia": "La Plaza",
}

#: OSM `shop` values that already describe a whole supermarket.
STORE_SHOPS = frozenset({"supermarket", "hypermarket"})

# Brand or name spellings a chain is known by, for the Overpass regex that finds a chain-named
# building without a `shop` tag. It may over-match: `chain_for_tags` filters the aliases exactly.
CHAIN_SEARCH = "merc[aá]dona|d[ií]a|alimerka|lidl|alcampo|leclerc|lupa|carrefour|gadis|claudio|aldi"

# Fallback `name` when OSM does not name the store (same names as the seed).
CHAIN_NAMES: dict[str, str] = {
    "mercadona": "Mercadona",
    "carrefour": "Carrefour",
    "dia": "Dia",
    "alcampo": "Alcampo",
    "gadis": "Gadis",
    "lupa": "Lupa",
    "alimerka": "Alimerka",
    "aldi": "Aldi",
    "lidl": "Lidl",
    "eleclerc": "E.Leclerc",
}


@dataclass(frozen=True, slots=True)
class StoreObservation:
    """One supermarket of a known chain, ready to be persisted."""

    osm_id: str
    chain_code: str
    name: str
    format: str | None
    address: str | None
    lon: float
    lat: float
    opening_hours: str | None


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """The search area of the Overpass query, in degrees."""

    south: float
    west: float
    north: float
    east: float

    @classmethod
    def parse(cls, value: str) -> BoundingBox:
        """Build the box from the `south,west,north,east` setting."""
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 4:
            raise ValueError(f"a bounding box needs four numbers, not {len(parts)}: {value!r}")
        try:
            south, west, north, east = (float(part) for part in parts)
        except ValueError as exc:
            raise ValueError(f"a bounding box needs four numbers: {value!r}") from exc
        if south >= north or west >= east:
            raise ValueError(f"a bounding box needs south < north and west < east: {value!r}")
        return cls(south=south, west=west, north=north, east=east)

    def query(self) -> str:
        """The Overpass QL query: supermarkets, hypermarkets and chain-named buildings."""
        corners = f"{self.south},{self.west},{self.north},{self.east}"
        return (
            f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];\n"
            f'nwr["shop"~"^(supermarket|hypermarket)$"]({corners});\n'
            f'nwr["building"]["brand"~"{CHAIN_SEARCH}",i]({corners});\n'
            f'nwr["building"]["name"~"{CHAIN_SEARCH}",i]({corners});\n'
            "out center tags;"
        )


def normalize(value: str | None) -> str:
    """Case, accent and punctuation insensitive form used for every tag comparison."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed.casefold() if character.isalnum())


def chain_for_tags(tags: dict[str, str]) -> str | None:
    """The chain code of `tags` by brand, then name, or None when it is not one of the ten."""
    for key in ("brand", "name"):
        value = tags.get(key)
        if value and (code := CHAIN_ALIASES.get(normalize(value))) is not None:
            return code
    return None


def store_format(tags: dict[str, str]) -> str | None:
    """The brand variant when it names a format ("Express"), else the OSM `shop` value."""
    for key in ("brand", "name"):
        value = tags.get(key)
        if value and (variant := STORE_FORMATS.get(normalize(value))) is not None:
            return variant
    return tags.get("shop") or None


def build_address(tags: dict[str, str]) -> str | None:
    """The postal address from the `addr:*` tags OSM has, or None when it has none."""
    street = " ".join(
        part for part in (tags.get("addr:street"), tags.get("addr:housenumber")) if part
    )
    locality = " ".join(part for part in (tags.get("addr:postcode"), tags.get("addr:city")) if part)
    return ", ".join(part for part in (street, locality) if part) or None


def is_store(tags: dict[str, str]) -> bool:
    """True for an OSM supermarket, or for a chain-named building without a `shop` tag."""
    if "shop" in tags:
        return tags["shop"] in STORE_SHOPS
    return "building" in tags


def parse_elements(elements: Iterable[dict[str, Any]]) -> tuple[StoreObservation, ...]:
    """Keep the supermarkets of the ten chains, and their buildings tagged only by name."""
    observations: dict[str, StoreObservation] = {}
    for element in elements:
        kind, element_id = element.get("type"), element.get("id")
        if not kind or element_id is None:
            continue
        tags = element.get("tags") or {}
        if not is_store(tags):
            continue
        chain_code = chain_for_tags(tags)
        if chain_code is None:
            continue
        position = _position(element)
        if position is None:
            continue
        lon, lat = position
        osm_id = f"{kind}/{element_id}"
        observations[osm_id] = StoreObservation(
            osm_id=osm_id,
            chain_code=chain_code,
            name=(tags.get("name") or "").strip() or CHAIN_NAMES[chain_code],
            # A building without a `shop` tag does not know its format.
            format=None if "shop" not in tags else store_format(tags),
            address=build_address(tags),
            lon=lon,
            lat=lat,
            opening_hours=tags.get("opening_hours"),
        )
    return tuple(observations.values())


def _position(element: dict[str, Any]) -> tuple[float, float] | None:
    """A node carries `lon`/`lat`; a way or a relation carries them in its `center`."""
    if element.get("type") == "node":
        lon, lat = element.get("lon"), element.get("lat")
    else:
        center = element.get("center") or {}
        lon, lat = center.get("lon"), center.get("lat")
    if lon is None or lat is None:
        return None
    return float(lon), float(lat)


def user_agent() -> str:
    """Overpass asks every client to identify itself: `smart-basket/<package version>`."""
    try:
        package_version = version("smart-basket")
    except PackageNotFoundError:
        package_version = "unknown"
    return f"smart-basket/{package_version}"


class OverpassError(RuntimeError):
    """The Overpass answer could not be obtained; the import is then skipped."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error = message


class OverpassClient:
    """Posts one Overpass query, politely, with a single retry for timeouts and 5xx."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        url: str = DEFAULT_OVERPASS_URL,
        timeout: float = OVERPASS_TIMEOUT_SECONDS,
        retries: int = 1,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._url = url
        self._retries = retries

    def __enter__(self) -> OverpassClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch(self, bbox: BoundingBox) -> list[dict[str, Any]]:
        """The Overpass elements inside `bbox`, or `OverpassError` after the retries."""
        query = bbox.query()
        for attempt in range(self._retries + 1):
            try:
                response = self._client.post(
                    self._url, data={"data": query}, headers={"User-Agent": user_agent()}
                )
            except httpx.TimeoutException as exc:
                if attempt == self._retries:
                    raise OverpassError(f"{self._url}: timeout: {exc}") from exc
                continue
            except httpx.HTTPError as exc:
                raise OverpassError(f"{self._url}: {exc}") from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._retries:
                    raise OverpassError(f"{self._url}: HTTP {response.status_code}")
                continue
            if response.status_code >= 400:
                raise OverpassError(f"{self._url}: HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise OverpassError(f"{self._url}: the answer is not JSON") from exc
            elements = payload.get("elements") if isinstance(payload, dict) else None
            if not isinstance(elements, list):
                raise OverpassError(f"{self._url}: the answer has no elements list")
            return elements
        raise AssertionError("unreachable")


def fetch_stores(client: OverpassClient, bbox: BoundingBox) -> tuple[StoreObservation, ...]:
    """Fetch the Overpass answer and keep the supermarkets of the ten chains."""
    return parse_elements(client.fetch(bbox))
