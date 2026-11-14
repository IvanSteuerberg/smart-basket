"""Catalog, list interpretation and geocoding behind one router (decision 0008).

The web browses the seeded taxonomy, searches it, sends a free-text list and asks for an
address. Everything here is read-only over the database; the LLM and Nominatim failures never
surface as a bare 500.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import Row, bindparam, text
from sqlalchemy.orm import Session

from smart_basket.api.lexicon_cache import preprocessor_for, search_forms_for
from smart_basket.api.products import _unit_price
from smart_basket.config import get_settings
from smart_basket.db.engine import get_session
from smart_basket.geo.nominatim import GeocodingError, NominatimGeocoder
from smart_basket.llm.base import LLMError, LLMProvider, provider_from_settings
from smart_basket.llm.interpret import Interpretation, interpret_unresolved
from smart_basket.preprocessor import PreprocessedItem, Preprocessor, PreprocessResult
from smart_basket.preprocessor.text import fold

router = APIRouter(tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]

SEARCH_MIN_SCORE = 60.0
SEARCH_LIMIT = 10
SEARCH_MIN_LENGTH = 2
GEOCODE_MIN_LENGTH = 3
SEARCH_SHORT_ERROR = "La búsqueda debe tener al menos 2 caracteres."
GEOCODE_SHORT_ERROR = "La dirección debe tener al menos 3 caracteres."
GEOCODING_ERROR = "No se ha podido buscar la dirección. Prueba a marcar el punto en el mapa."

_CATEGORIES_SQL = text(
    "select c.id, c.key, c.name, c.parent_id, c.level, c.base_unit, c.forms, c.is_vague,"
    "  coalesce(p.products, 0) as products"
    " from category c"
    " left join ("
    "   select cc.ancestor_id as category_id, count(distinct cp.id) as products"
    "   from category_closure cc"
    "   join chain_category ccat on ccat.category_id = cc.descendant_id"
    "   join chain_product cp on cp.chain_category_id = ccat.id and cp.is_active"
    "   join chain_product_zone cpz"
    "     on cpz.chain_product_id = cp.id and cpz.is_available"
    "   group by cc.ancestor_id"
    " ) p on p.category_id = c.id"
    " order by c.name, c.key"
)


# Catalog -------------------------------------------------------------------


class LeafCategory(BaseModel):
    key: str
    name: str
    base_unit: str | None
    products: int


class GroupCategory(BaseModel):
    key: str
    name: str
    vague: bool
    products: int
    children: list[LeafCategory]


class Section(BaseModel):
    key: str
    name: str
    children: list[GroupCategory]


class CategoriesResponse(BaseModel):
    sections: list[Section]


def _is_stale(name: str, forms: Sequence[str]) -> bool:
    return not forms and "(obsoleta " in name and name.endswith(")")


def _order(row: Row) -> tuple[str, str]:
    return (fold(row.name), row.key)


def _checked_query(q: str, minimum: int, error: str) -> str:
    """`q` without surrounding blanks, or a 422 when it is too short once stripped."""
    query = q.strip()
    if len(query) < minimum:
        raise HTTPException(status_code=422, detail=error)
    return query


def _category_rows(session: Session) -> list[Row]:
    return [row for row in session.execute(_CATEGORIES_SQL) if not _is_stale(row.name, row.forms)]


@router.get("/categories", response_model=CategoriesResponse)
def categories(session: SessionDep) -> CategoriesResponse:
    """The taxonomy as sections, groups and leaves, with product counts."""
    rows = _category_rows(session)
    by_id = {row.id: row for row in rows}
    children: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        # A category whose parent was left out (a stale one) is left out with it.
        parent = by_id.get(row.parent_id) if row.parent_id is not None else None
        if parent is not None:
            children[parent.id].append(row)
    sections = [
        Section(
            key=section.key,
            name=section.name,
            children=[
                GroupCategory(
                    key=group.key,
                    name=group.name,
                    vague=group.is_vague,
                    products=group.products,
                    children=[
                        LeafCategory(
                            key=leaf.key,
                            name=leaf.name,
                            base_unit=leaf.base_unit,
                            products=leaf.products,
                        )
                        for leaf in sorted(children[group.id], key=_order)
                    ],
                )
                for group in sorted(children[section.id], key=_order)
            ],
        )
        for section in sorted((row for row in rows if row.parent_id is None), key=_order)
    ]
    return CategoriesResponse(sections=sections)


# Search --------------------------------------------------------------------


class SearchResult(BaseModel):
    key: str
    name: str
    kind: Literal["leaf", "group"]
    path: str


class SearchResponse(BaseModel):
    results: list[SearchResult]


def _ancestor_path(row: Row, by_id: dict[int, Row]) -> str:
    names: list[str] = []
    parent_id = row.parent_id
    while parent_id is not None:
        ancestor = by_id.get(parent_id)
        if ancestor is None:
            break
        names.append(ancestor.name)
        parent_id = ancestor.parent_id
    return " › ".join(reversed(names))


def _match_tier(query: str, forms: Sequence[str]) -> int:
    """2 for an exact form, 1 when one starts with the query, 0 for a fuzzy match alone."""
    if query in forms:
        return 2
    return 1 if any(form.startswith(query) for form in forms) else 0


@router.get("/search", response_model=SearchResponse)
def search(q: Annotated[str, Query()], session: SessionDep) -> SearchResponse:
    """Categories whose forms or name resemble `q`: exact and prefix matches first, then
    leaves before groups and by name."""
    query = fold(_checked_query(q, SEARCH_MIN_LENGTH, SEARCH_SHORT_ERROR))
    rows = _category_rows(session)
    by_id = {row.id: row for row in rows}
    with_children = {row.parent_id for row in rows}
    folded = search_forms_for(session)
    scored: list[tuple[int, float, Row]] = []
    for row in rows:
        forms = folded.get(row.id, (fold(row.name),))
        score = max(fuzz.WRatio(query, form) for form in forms if form)
        if score >= SEARCH_MIN_SCORE:
            scored.append((_match_tier(query, forms), score, row))
    scored.sort(
        key=lambda pair: (
            -pair[0],
            -pair[1],
            0 if pair[2].id not in with_children else 1,
            fold(pair[2].name),
            pair[2].key,
        )
    )
    results = [
        SearchResult(
            key=row.key,
            name=row.name,
            kind="leaf" if row.id not in with_children else "group",
            path=_ancestor_path(row, by_id),
        )
        for _, _, row in scored[:SEARCH_LIMIT]
    ]
    return SearchResponse(results=results)


# Interpretation ------------------------------------------------------------


class InterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class OptionOut(BaseModel):
    """One choice a vague category offers: a leaf, its cheapest unit price and a photo."""

    category_key: str
    name: str
    image_url: str | None
    from_unit_price: str
    base_unit: str | None


class InterpretedItem(BaseModel):
    line: int
    text: str
    item: str
    quantity: str
    unit: Literal["ud", "kg", "g", "l", "ml"]
    category_key: str | None
    category_name: str | None
    brand: str | None
    alternatives: list[str]
    resolved: bool
    needs_llm: bool
    #: Photo of the cheapest product per unit of its category and descendants, if any.
    image_url: str | None
    options: list[OptionOut]


class InterpretResponse(BaseModel):
    items: list[InterpretedItem]
    llm_used: bool
    degraded: bool


def get_llm_provider() -> LLMProvider | None:
    """The configured provider, or None (degraded mode) when it cannot be built."""
    try:
        return provider_from_settings(get_settings())
    except LLMError:
        return None


def _quantity_text(value: Decimal | int | float) -> str:
    """A JSON-safe decimal string: "1", "0.5" or the full precision of a fraction."""
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(number.normalize(), "f")


def _category_key(preprocessor: Preprocessor, item: str) -> str | None:
    items = preprocessor.preprocess(item).items
    return items[0].generic_key if items else None


def _source_items(
    result: PreprocessResult, interpretation: Interpretation
) -> list[tuple[PreprocessedItem | None, int]]:
    """Which rule-based item (and line) each merged item comes from; None for LLM items.

    `interpret_unresolved` keeps resolved items in order and replaces the unresolved block at
    the position of the first unresolved line, so the merged list can be aligned back.
    """
    if not interpretation.llm_used:
        return [(item, item.line) for item in result.items]
    first = next(index for index, item in enumerate(result.items) if not item.resolved)
    before = [(item, item.line) for item in result.items[:first]]
    after = [(item, item.line) for item in result.items[first:] if item.resolved]
    unresolved = [item for item in result.items if not item.resolved]
    count = max(len(interpretation.items) - len(before) - len(after), 0)
    block = [(None, unresolved[min(k, len(unresolved) - 1)].line) for k in range(count)]
    return before + block + after


def _interpreted_item(
    preprocessor: Preprocessor,
    item: dict[str, Any],
    source: PreprocessedItem | None,
    line: int,
    key: str | None,
    vague: bool,
    image_url: str | None,
    options: Sequence[OptionOut],
) -> InterpretedItem:
    text = str(item.get("item", ""))
    term = preprocessor.generic_by_key.get(key) if key is not None else None
    return InterpretedItem(
        line=line,
        text=source.raw if source is not None else text,
        item=text,
        quantity=_quantity_text(source.quantity if source is not None else item.get("quantity", 1)),
        unit=source.unit if source is not None else item.get("unit", "ud"),
        category_key=key,
        category_name=term.name if term is not None else None,
        brand=source.brand if source is not None else item.get("brand"),
        alternatives=list(source.alternatives) if source is not None else [],
        resolved=(source.resolved if source is not None else True) and not vague,
        needs_llm=source.needs_llm if source is not None else False,
        image_url=image_url,
        options=list(options),
    )


def _item_key(
    preprocessor: Preprocessor, item: dict[str, Any], source: PreprocessedItem | None
) -> str | None:
    # A rule-resolved line already knows its category; only LLM items are parsed again.
    if source is not None:
        return source.generic_key
    return _category_key(preprocessor, str(item.get("item", "")))


def _child_counts(session: Session, parent_ids: Sequence[int]) -> dict[int, list[Row]]:
    """Direct children of the given nodes with the number of priced products below them."""
    if not parent_ids:
        return {}
    rows = session.execute(
        text(
            """
            select p.id as parent_id, c.id as child_id, c.key, c.name,
                   count(distinct cp.id) as products
            from category p
            join category c on c.parent_id = p.id
            join category_closure cl on cl.ancestor_id = c.id
            join (
                select cp.id, coalesce(canon.category_id, ccat.category_id) as category_id
                from chain_product cp
                left join canonical_product canon on canon.id = cp.canonical_id
                left join chain_category ccat on ccat.id = cp.chain_category_id
                where cp.is_active
            ) cp on cp.category_id = cl.descendant_id
            join chain_product_zone cpz
              on cpz.chain_product_id = cp.id and cpz.is_available
            join price_current pc
              on pc.chain_product_id = cp.id and pc.zone_id = cpz.zone_id
            where p.id in :parents
            group by p.id, c.id, c.key, c.name
            having count(distinct cp.id) > 0
            """
        ).bindparams(bindparam("parents", expanding=True)),
        {"parents": list(parent_ids)},
    ).mappings()
    grouped: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row["parent_id"]].append(row)
    return grouped


def _option_prices(session: Session, keys: set[str]) -> dict[str, dict[str, Any]]:
    """Cheapest priced product per category (and descendants): unit price, photo and base unit."""
    if not keys:
        return {}
    rows = session.execute(
        text(
            """
            select opt.key as option_key, opt.name as option_name,
                   opt.base_unit as option_base_unit,
                   cp.id as product_id, cp.name, cp.base_quantity, cp.base_unit,
                   cp.image_url, pc.price
            from category opt
            join category_closure cl on cl.ancestor_id = opt.id
            join (
                select cp.id, coalesce(canon.category_id, ccat.category_id) as category_id
                from chain_product cp
                left join canonical_product canon on canon.id = cp.canonical_id
                left join chain_category ccat on ccat.id = cp.chain_category_id
                where cp.is_active
            ) eff on eff.category_id = cl.descendant_id
            join chain_product cp on cp.id = eff.id
            join chain_product_zone cpz
              on cpz.chain_product_id = cp.id and cpz.is_available
            join price_current pc
              on pc.chain_product_id = cp.id and pc.zone_id = cpz.zone_id
            where opt.key in :keys
            """
        ).bindparams(bindparam("keys", expanding=True)),
        {"keys": sorted(keys)},
    ).mappings()
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        price = _unit_price(row["price"], row["base_quantity"], row["base_unit"])
        if price is None:
            continue
        candidate = {
            "price": Decimal(price),
            "product_id": row["product_id"],
            "image_url": row["image_url"],
            "base_unit": row["option_base_unit"] or row["base_unit"],
            "name": row["option_name"],
            "from_unit_price": price,
        }
        current = best.get(row["option_key"])
        if current is None or (candidate["price"], candidate["product_id"]) < (
            current["price"],
            current["product_id"],
        ):
            best[row["option_key"]] = candidate
    return best


def _category_options(session: Session, keys: set[str]) -> dict[str, list[OptionOut]]:
    """The options each vague category offers, with the cheapest unit price and its photo.

    An explicit `options` list keeps its order; a vague node without one offers at most eight
    direct children with priced products, most products first and then by name.
    """
    if not keys:
        return {}
    rows = (
        session.execute(
            text(
                "select id, key, name, base_unit, options from category where key in :keys"
            ).bindparams(bindparam("keys", expanding=True)),
            {"keys": sorted(keys)},
        )
        .mappings()
        .all()
    )
    children = _child_counts(session, [row["id"] for row in rows if not row["options"]])
    option_keys: dict[str, list[str]] = {}
    for row in rows:
        if row["options"]:
            option_keys[row["key"]] = list(row["options"])
            continue
        candidates = sorted(
            children.get(row["id"], []),
            key=lambda child: (-child["products"], fold(child["name"]), child["key"]),
        )
        option_keys[row["key"]] = [child["key"] for child in candidates[:8]]
    prices = _option_prices(session, {key for keys_ in option_keys.values() for key in keys_})
    options: dict[str, list[OptionOut]] = {}
    for key, category_keys in option_keys.items():
        offered = []
        for category_key in category_keys:
            price = prices.get(category_key)
            if price is None:
                continue
            offered.append(
                OptionOut(
                    category_key=category_key,
                    name=price["name"],
                    image_url=price["image_url"],
                    from_unit_price=price["from_unit_price"],
                    base_unit=price["base_unit"],
                )
            )
        options[key] = offered
    return options


@router.post("/interpret", response_model=InterpretResponse)
def interpret(
    body: InterpretRequest,
    session: SessionDep,
    provider: Annotated[LLMProvider | None, Depends(get_llm_provider)],
) -> InterpretResponse:
    """Turn a free-text list into items, asking the LLM only for the unresolved lines."""
    preprocessor = preprocessor_for(session)
    result = preprocessor.preprocess(body.text)
    # The LLM can take seconds: release the connection before waiting on it.
    session.close()
    interpretation = interpret_unresolved(result, provider)
    sources = _source_items(result, interpretation)
    keys = [
        _item_key(preprocessor, item, source)
        for item, (source, _) in zip(interpretation.items, sources, strict=True)
    ]
    vague_keys = {
        key
        for key in keys
        if key is not None and getattr(preprocessor.generic_by_key.get(key), "vague", False)
    }
    options = _category_options(session, vague_keys)
    # The cheapest priced product of each line's category gives its photo, as for options.
    prices = _option_prices(session, {key for key in keys if key is not None})
    images = {key: price["image_url"] for key, price in prices.items()}
    items = [
        _interpreted_item(
            preprocessor,
            item,
            source,
            line,
            key,
            key in vague_keys,
            images.get(key),
            options.get(key, ()),
        )
        for item, key, (source, line) in zip(interpretation.items, keys, sources, strict=True)
    ]
    return InterpretResponse(
        items=items, llm_used=interpretation.llm_used, degraded=interpretation.degraded
    )


# Geocoding -----------------------------------------------------------------


class GeocodeResult(BaseModel):
    label: str
    lat: float
    lon: float


class GeocodeResponse(BaseModel):
    results: list[GeocodeResult]


@lru_cache
def get_geocoder() -> NominatimGeocoder:
    """The process-wide Nominatim client, with its rate limiter and cache."""
    return NominatimGeocoder(get_settings().nominatim_url)


@router.get("/geocode", response_model=GeocodeResponse)
def geocode(
    q: Annotated[str, Query()],
    geocoder: Annotated[NominatimGeocoder, Depends(get_geocoder)],
) -> GeocodeResponse:
    """Up to five places inside León for an address; a failed lookup is a 503."""
    query = _checked_query(q, GEOCODE_MIN_LENGTH, GEOCODE_SHORT_ERROR)
    try:
        places = geocoder.search(query)
    except GeocodingError:
        raise HTTPException(status_code=503, detail=GEOCODING_ERROR) from None
    return GeocodeResponse(
        results=[GeocodeResult(label=place.label, lat=place.lat, lon=place.lon) for place in places]
    )
