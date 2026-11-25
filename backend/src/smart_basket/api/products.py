"""Supermarket-style catalog: sections, products and product detail (iteration 12, task E4).

The web browses the chain products by taxonomy section, searches them by folded text and opens a
product with its alternatives. Prices are read from the zone of each chain's active stores in
León, so a product is listed only when that zone sells it with a current price. Everything here
is read-only and answerable in a couple of queries.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.lexicon_cache import search_forms_for
from smart_basket.brands import Brands, brands_for
from smart_basket.config import get_settings
from smart_basket.db.engine import get_session
from smart_basket.preprocessor.rules_es import CONNECTORS
from smart_basket.preprocessor.text import tokenize
from smart_basket.recommender.explanation import decimal_text

router = APIRouter(tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]

#: Unit prices keep the four decimals of `price_current.price_per_unit`.
UNIT_PRICE_QUANTUM = Decimal("0.0001")
SORTS = ("relevance", "popular", "unit_price", "price", "name")
MAX_PAGE_SIZE = 60
ALTERNATIVES_LIMIT = 12
#: The sections summary changes only when the catalog changes; a short TTL avoids rebuilding it.
SECTIONS_TTL_SECONDS = 60.0

SIZE_ERROR = "El tamaño de la página debe estar entre 1 y 60."
PAGE_ERROR = "La página debe ser al menos 1."
SORT_ERROR = "El orden debe ser relevance, popular, unit_price, price o name."
SECTION_ERROR = "La sección no existe."
CATEGORY_ERROR = "La categoría no existe."
PRODUCT_ERROR = "El producto no existe o no está disponible."
NEAR_PAIR_ERROR = "Debes indicar la latitud y la longitud juntas."
MODE_ERROR = "El modo debe ser walk o car."
LATITUDE_ERROR = "La latitud debe estar entre -90 y 90."
LONGITUDE_ERROR = "La longitud debe estar entre -180 y 180."
MIN_PRICE_ERROR = "El precio mínimo no puede ser negativo."
MAX_PRICE_ERROR = "El precio máximo no puede ser negativo."
PRICE_RANGE_ERROR = "El precio mínimo no puede ser mayor que el precio máximo."
TRAVEL_MODES = ("walk", "car")

#: The zone of each chain's active stores in León; ties keep the lowest zone id.
_CHAIN_ZONE = """
with store_zone as (
    select s.chain_id, s.zone_id, count(*) as stores
    from store s
    where s.is_active
    group by s.chain_id, s.zone_id
),
chosen as (
    select distinct on (chain_id) chain_id, zone_id
    from store_zone
    order by chain_id, stores desc, zone_id
)
"""

#: Active product joined with its chain and chosen zone with a current price.
_ACTIVE_PRICED_PRODUCT_FROM = """
from chain_product cp
join chain ch on ch.id = cp.chain_id
join chosen cz on cz.chain_id = cp.chain_id
join chain_product_zone cpz
    on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
join price_current pc
    on pc.chain_product_id = cp.id and pc.zone_id = cz.zone_id
"""

#: Whether a promotion of the product's chain is active today in the product's chosen zone.
#: A promotion with rows in `promotion_zone` counts only for those zones; one without rows is
#: chain-wide. The `not exists ... or exists ...` form keeps a promotion of another zone out.
_PROMO_ACTIVE_SQL = """
exists (
    select 1
    from promotion pr
    join promotion_target pt on pt.promotion_id = pr.id
    where pr.chain_id = cp.chain_id
      and pr.valid @> current_date
      and (
          not exists (
              select 1 from promotion_zone pz
              where pz.promotion_id = pr.id
          )
          or exists (
              select 1 from promotion_zone pz
              where pz.promotion_id = pr.id and pz.zone_id = cz.zone_id
          )
      )
      and (
          pt.chain_product_id = cp.id
          or (pt.canonical_id is not null and pt.canonical_id = cp.canonical_id)
          or (pt.category_id is not null and pt.category_id = ec.id)
      )
)
"""

#: A listed product: active and available in its chain's zone, with a current price.
_PRODUCT_COLUMNS = f"""
    cp.id, cp.name, cp.packaging, cp.image_url, cp.base_quantity, cp.base_unit,
    cp.pack_count, cp.dietary_tags,
    cp.chain_id, ch.name as chain_name, pc.price,
    cp.canonical_id, canon.name as canonical_name,
    ec.id as category_id, ec.key as category_key, ec.name as category_name,
    ec.exact_only,
    ({_PROMO_ACTIVE_SQL}) as on_promo
"""
_PRODUCT_FROM = (
    _ACTIVE_PRICED_PRODUCT_FROM
    + """
left join canonical_product canon on canon.id = cp.canonical_id
left join chain_category ccat on ccat.id = cp.chain_category_id
join category ec on ec.id = coalesce(canon.category_id, ccat.category_id)
"""
)

_ORDERS = {
    # Same rule as `_unit_price`: a product counted by units without a size is priced per unit;
    # one weighed or measured without a size has no unit price and goes last. A multipack's
    # `base_quantity` is the size of one item, so its total size is `base_quantity * pack_count`.
    "unit_price": (
        "(cp.base_quantity is null and cp.base_unit is distinct from 'ud'), "
        "coalesce(pc.price / nullif("
        "cp.base_quantity * greatest(coalesce(cp.pack_count, 1), 1), 0), "
        "case when cp.base_unit = 'ud' then pc.price end), "
        "cp.name, cp.id"
    ),
    "price": "pc.price, cp.name, cp.id",
    "name": "cp.name, cp.id",
    # Popularity: how many chains sell the product's canonical, then the package price.
    "popular": (
        "coalesce((select count(distinct cp2.chain_id) from chain_product cp2"
        " where cp2.canonical_id = cp.canonical_id and cp2.is_active), 0) desc,"
        " pc.price, cp.name, cp.id"
    ),
}


#: The product name folded the way `smart_basket.preprocessor.text.fold` does.
def _fold_sql(col: str) -> str:
    return f"translate(lower({col}), 'áàäâãéèëêíìïîóòöôõúùüûñç', 'aaaaaeeeeiiiiooooouuuunc')"


_FOLDED_NAME = _fold_sql("cp.name")

#: Characters with a meaning inside a PostgreSQL regular expression (the hyphen is literal).
_REGEX_SPECIAL = frozenset(".^$*+?()[]{}|\\")

_SECTION_COUNTS_SQL = (
    _CHAIN_ZONE
    + """
select cl.ancestor_id as section_id, count(distinct cp.id) as products
from category section
join category_closure cl on cl.ancestor_id = section.id
join chain_product cp on cp.is_active
join chosen cz on cz.chain_id = cp.chain_id
join chain_product_zone cpz
    on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
join price_current pc
    on pc.chain_product_id = cp.id and pc.zone_id = cz.zone_id
left join canonical_product canon on canon.id = cp.canonical_id
left join chain_category ccat on ccat.id = cp.chain_category_id
where section.parent_id is null
  and cl.descendant_id = coalesce(canon.category_id, ccat.category_id)
group by cl.ancestor_id
"""
)

#: One representative photo per top-level section, chosen entirely in SQL: the photo of the
#: lowest product id of the most common canonical (or leaf category) holding a photo. Canonical
#: ids and category ids are different id spaces, so `by_canonical` keeps them apart.
_SECTION_PHOTOS_SQL = (
    _CHAIN_ZONE
    + """,
section_products as (
    select cl.ancestor_id as section_id, cp.id as product_id, cp.image_url,
           cp.canonical_id is not null as by_canonical,
           coalesce(cp.canonical_id, canon.category_id, ccat.category_id) as node_id
    from category section
    join category_closure cl on cl.ancestor_id = section.id
    join chain_product cp on cp.is_active
    join chosen cz on cz.chain_id = cp.chain_id
    join chain_product_zone cpz
        on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
    join price_current pc
        on pc.chain_product_id = cp.id and pc.zone_id = cz.zone_id
    left join canonical_product canon on canon.id = cp.canonical_id
    left join chain_category ccat on ccat.id = cp.chain_category_id
    where section.parent_id is null
      and cp.image_url is not null
      and cl.descendant_id = coalesce(canon.category_id, ccat.category_id)
),
photo_counts as (
    select section_id, by_canonical, node_id,
           count(*) as photos, min(product_id) as first_id
    from section_products
    group by section_id, by_canonical, node_id
),
chosen_group as (
    select distinct on (section_id) section_id, by_canonical, node_id
    from photo_counts
    order by section_id, photos desc, first_id
)
select distinct on (sp.section_id) sp.section_id, sp.image_url
from section_products sp
join chosen_group cg
    on cg.section_id = sp.section_id
    and cg.by_canonical = sp.by_canonical
    and cg.node_id = sp.node_id
order by sp.section_id, sp.product_id
"""
)


# Response models -----------------------------------------------------------


class SectionSummary(BaseModel):
    key: str
    name: str
    products: int
    image_url: str | None


class SectionsResponse(BaseModel):
    sections: list[SectionSummary]


class CanonicalOut(BaseModel):
    id: int
    name: str
    category_key: str
    category_name: str
    #: Only concrete products are bought in this category (shades): never swapped.
    exact_only: bool


class ProductOut(BaseModel):
    id: int
    name: str
    brand: str | None
    private_label: bool
    packaging: str | None
    image_url: str | None
    chain: str
    price: str
    unit_price: str | None
    base_unit: str | None
    base_quantity: str | None
    canonical: CanonicalOut | None
    #: Wave 0 contract: populated from `chain_product.dietary_tags` when available.
    dietary_tags: list[str] = Field(default_factory=list)
    #: True when a promotion of the chain is valid today in the product's chosen zone.
    on_promo: bool = False


class ProductsResponse(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    size: int


class ProductDetail(ProductOut):
    alternatives: list[ProductOut]


# Helpers -------------------------------------------------------------------


def _regex_escape(word: str) -> str:
    return "".join(
        "\\" + character if character in _REGEX_SPECIAL else character for character in word
    )


def _word_regex_body(word: str) -> str:
    """Alternation of `word` and its -s/-es plural or singular variants."""
    variants = {word, word + "s", word + "es"}
    if word.endswith("s") and len(word) > 1:
        variants.add(word[:-1])
    if word.endswith("es") and len(word) > 2:
        variants.add(word[:-2])
    return "|".join(
        _regex_escape(variant) for variant in sorted(variants, key=len, reverse=True) if variant
    )


def _word_pattern(word: str) -> str:
    """Whole-word pattern for `word`, tolerating a plural -s or -es on either side."""
    body = _word_regex_body(word)
    return rf"(^|[^a-z0-9])({body})([^a-z0-9]|$)"


def _start_pattern(word: str) -> str:
    """Start-of-string whole-word pattern for `word`, tolerating plural -s or -es."""
    body = _word_regex_body(word)
    return rf"^({body})([^a-z0-9]|$)"


def _phrase_pattern(phrase: str) -> str:
    """Whole-word pattern for a phrase, tolerating a plural -s or -es on each word."""
    body = r"[^a-z0-9]+".join(f"({_word_regex_body(word)})" for word in phrase.split() if word)
    return rf"(^|[^a-z0-9])({body})([^a-z0-9]|$)"


def _relevance_rank_sql(name_columns: Sequence[str], has_categories: bool) -> str:
    """Deterministic relevance rank of `q` against the given folded name columns.

    Level 0 is an exact name match or a category-form match whose name starts with the query;
    level 1 is a canonical prefix match of the whole normalized phrase; level 2 is a category
    subtree match or a prefix match of the first word; level 3 is a plain all-words match.
    """
    folded = [_fold_sql(column) for column in name_columns]
    exact = " or ".join(f"{name} = :q_norm" for name in folded)
    phrase = " or ".join(f"{name} ~ :q_phrase" for name in folded)
    starts = " or ".join(f"{name} ~ :q_start" for name in folded)
    if has_categories:
        in_categories = (
            "ec.id in (select descendant_id from category_closure "
            "where ancestor_id = any(:q_categories))"
        )
        level_zero = f"({exact}) or ({in_categories} and ({starts}))"
        level_two = f"({in_categories}) or ({starts})"
    else:
        level_zero = exact
        level_two = starts
    return (
        f"(case when {level_zero} then 0 when {phrase} then 1 when {level_two} then 2 else 3 end)"
    )


def _query_tokens(q: str) -> tuple[str, ...]:
    """Every folded word or number of `q`, connectors included."""
    return tuple(token.key for token in tokenize(q) if token.kind in ("word", "num"))


def _query_words(q: str) -> tuple[str, ...]:
    """Folded content tokens of `q`; connectors such as "de" carry no product meaning."""
    return tuple(word for word in _query_tokens(q) if word not in CONNECTORS)


def search_params(
    q: str,
    forms: Mapping[int, Iterable[str]],
    params: dict[str, Any],
) -> tuple[tuple[str, ...], list[int]]:
    """Folded content tokens, regex patterns and matching category IDs for `q`."""
    tokens = _query_tokens(q)
    query = tuple(word for word in tokens if word not in CONNECTORS)
    if not query:
        return (), []
    for index, word in enumerate(query):
        params[f"q_word_{index}"] = _word_pattern(word)
    params["q_start"] = _start_pattern(query[0])
    params["q_norm"] = " ".join(tokens)
    params["q_phrase"] = (
        "^" + "[^a-z0-9]+".join(f"({_word_regex_body(word)})" for word in tokens) + r"([^a-z0-9]|$)"
    )
    normalized = " ".join(query)
    category_ids = sorted(
        category_id
        for category_id, category_forms in forms.items()
        if any(form.strip() == normalized for form in category_forms)
    )
    if category_ids:
        params["q_categories"] = category_ids
    return query, category_ids


def _search_sql(query: tuple[str, ...], category_ids: list[int]) -> str | None:
    """Every word in the product name, or a match of `q` against the category's forms."""
    if not query:
        return None
    name_parts = [f"{_FOLDED_NAME} ~ :q_word_{index}" for index in range(len(query))]
    if not category_ids:
        return f"({' and '.join(name_parts)})"
    # A query naming a group ("lacteos") matches the products of every leaf below it.
    return (
        f"(({' and '.join(name_parts)}) or ec.id in (select descendant_id from category_closure "
        "where ancestor_id = any(:q_categories)))"
    )


def _taxonomy_conditions(
    section_id: int | None,
    category_id: int | None,
    params: dict[str, Any],
) -> list[str]:
    conditions: list[str] = []
    if section_id is not None:
        params["section_id"] = section_id
        conditions.append(
            "ec.id in (select descendant_id from category_closure where ancestor_id = :section_id)"
        )
    if category_id is not None:
        params["category_id"] = category_id
        conditions.append(
            "ec.id in (select descendant_id from category_closure where ancestor_id = :category_id)"
        )
    return conditions


@dataclass(frozen=True, slots=True)
class CatalogFilters:
    """Product-level filters shared by the product and canonical listings."""

    chains: frozenset[str]
    brand: str | None
    private_label: bool | None
    dietary: tuple[str, ...]
    on_promo: bool | None
    min_price: Decimal | None
    max_price: Decimal | None


def _split_values(value: str | None) -> list[str]:
    """Comma-separated values, trimmed and lower-cased, in order and without repeats."""
    if not value:
        return []
    parts = (part.strip().lower() for part in value.split(","))
    return list(dict.fromkeys(part for part in parts if part))


def _chains_filter(chain: str | None, chains: str | None) -> frozenset[str]:
    """The deduplicated lowercase chain codes of `chain` and `chains` together."""
    return frozenset(_split_values(f"{chain or ''},{chains or ''}"))


def _validate_price_bounds(min_price: Decimal | None, max_price: Decimal | None) -> None:
    if min_price is not None and min_price < 0:
        raise HTTPException(status_code=422, detail=MIN_PRICE_ERROR)
    if max_price is not None and max_price < 0:
        raise HTTPException(status_code=422, detail=MAX_PRICE_ERROR)
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail=PRICE_RANGE_ERROR)


def _near_radius(near_lat: float | None, near_lon: float | None, mode: str | None) -> int | None:
    """Radius in metres of the origin search, or None when no coordinates were given."""
    if mode is not None and mode not in TRAVEL_MODES:
        raise HTTPException(status_code=422, detail=MODE_ERROR)
    if (near_lat is None) != (near_lon is None):
        raise HTTPException(status_code=422, detail=NEAR_PAIR_ERROR)
    if near_lat is None or near_lon is None:
        return None
    if not -90 <= near_lat <= 90:
        raise HTTPException(status_code=422, detail=LATITUDE_ERROR)
    if not -180 <= near_lon <= 180:
        raise HTTPException(status_code=422, detail=LONGITUDE_ERROR)
    settings = get_settings()
    return settings.walk_radius_m if (mode or "walk") == "walk" else settings.car_radius_m


def _chains_within_radius(
    session: Session, near_lat: float, near_lon: float, radius: int
) -> frozenset[str]:
    """Codes of the chains with an active store within `radius` metres of the origin."""
    rows = session.execute(
        text(
            "select distinct ch.code"
            " from store s"
            " join chain ch on ch.id = s.chain_id"
            " where s.is_active"
            "   and st_dwithin("
            "       s.geom, st_setsrid(st_makepoint(:lon, :lat), 4326)::geography, :radius)"
        ),
        {"lon": near_lon, "lat": near_lat, "radius": radius},
    ).scalars()
    return frozenset(rows)


def _brand_condition(brand: str, brands: Brands, params: dict[str, Any]) -> str:
    """Whole-word match of the brand's folded name or any of its aliases."""
    patterns = []
    for index, term in enumerate(sorted(brands.terms(brand))):
        key = f"brand_{index}"
        params[key] = _phrase_pattern(term)
        patterns.append(f"{_FOLDED_NAME} ~ :{key}")
    return f"({' or '.join(patterns)})"


def _private_label_condition(private_label: bool, brands: Brands, params: dict[str, Any]) -> str:
    """Keep (or exclude) the products naming one of their own chain's private labels."""
    clauses = []
    for index, (chain_id, labels) in enumerate(sorted(brands.private_label_terms().items())):
        chain_key = f"private_chain_{index}"
        params[chain_key] = chain_id
        patterns = []
        for label_index, label in enumerate(labels):
            key = f"private_label_{index}_{label_index}"
            params[key] = _phrase_pattern(" ".join(label))
            patterns.append(f"{_FOLDED_NAME} ~ :{key}")
        clauses.append(f"(cp.chain_id = :{chain_key} and ({' or '.join(patterns)}))")
    clause = f"({' or '.join(clauses)})" if clauses else "false"
    return clause if private_label else f"not {clause}"


def _product_conditions(
    filters: CatalogFilters,
    brands: Brands,
    params: dict[str, Any],
) -> list[str]:
    """SQL conditions for the product-level catalog filters (aliases cp, ch, cz, pc, ec)."""
    conditions: list[str] = []
    if filters.chains:
        params["chains"] = sorted(filters.chains)
        conditions.append("ch.code = any(:chains)")
    if filters.brand:
        conditions.append(_brand_condition(filters.brand, brands, params))
    if filters.private_label is not None:
        conditions.append(_private_label_condition(filters.private_label, brands, params))
    if filters.dietary:
        params["dietary"] = list(filters.dietary)
        conditions.append("cp.dietary_tags @> cast(:dietary as text[])")
    if filters.on_promo is not None:
        conditions.append(
            f"({_PROMO_ACTIVE_SQL})" if filters.on_promo else f"not ({_PROMO_ACTIVE_SQL})"
        )
    if filters.min_price is not None:
        params["min_price"] = filters.min_price
        conditions.append("pc.price >= :min_price")
    if filters.max_price is not None:
        params["max_price"] = filters.max_price
        conditions.append("pc.price <= :max_price")
    return conditions


def _category_id(session: Session, key: str, error: str) -> int:
    category_id = session.execute(
        text("select id from category where key = :key"), {"key": key}
    ).scalar_one_or_none()
    if category_id is None:
        raise HTTPException(status_code=422, detail=error)
    return category_id


def _unit_price(
    price: Decimal,
    quantity: Decimal | None,
    unit: str | None,
    pack_count: int | None = 1,
) -> str | None:
    """Price per base unit; `quantity` is the size of one pack item, so multiply by `pack_count`."""
    if quantity is None or quantity <= 0:
        return decimal_text(price) if unit == "ud" else None
    total = quantity * max(pack_count or 1, 1)
    return decimal_text((price / total).quantize(UNIT_PRICE_QUANTUM, rounding=ROUND_HALF_UP))


def _to_product(row: Mapping[str, Any], brands: Brands) -> ProductOut:
    canonical = None
    if row["canonical_id"] is not None:
        canonical = CanonicalOut(
            id=row["canonical_id"],
            name=row["canonical_name"],
            category_key=row["category_key"],
            category_name=row["category_name"],
            exact_only=row["exact_only"],
        )
    return ProductOut(
        id=row["id"],
        name=row["name"],
        brand=brands.brand_for(row["name"]),
        private_label=brands.is_private_label(row["chain_id"], row["name"]),
        packaging=row["packaging"],
        image_url=row["image_url"],
        chain=row["chain_name"],
        price=decimal_text(row["price"]),
        unit_price=_unit_price(
            row["price"], row["base_quantity"], row["base_unit"], row.get("pack_count")
        ),
        base_unit=row["base_unit"],
        base_quantity=(
            decimal_text(row["base_quantity"]) if row["base_quantity"] is not None else None
        ),
        canonical=canonical,
        dietary_tags=list(row.get("dietary_tags") or ()),
        on_promo=bool(row.get("on_promo")),
    )


class SectionsCache:
    """The sections summary, reused for `ttl_seconds`; tests call `reset` between databases."""

    def __init__(
        self,
        ttl_seconds: float = SECTIONS_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._value: SectionsResponse | None = None
        self._stored_at: float | None = None

    def get(self) -> SectionsResponse | None:
        with self._lock:
            if self._value is None or self._stored_at is None:
                return None
            if self._clock() - self._stored_at >= self.ttl_seconds:
                return None
            return self._value

    def set(self, value: SectionsResponse) -> None:
        with self._lock:
            self._value = value
            self._stored_at = self._clock()

    def reset(self) -> None:
        """Forget the cached summary; tests call it between databases."""
        with self._lock:
            self._value = None
            self._stored_at = None


default_sections_cache = SectionsCache()


# Routes --------------------------------------------------------------------


@router.get("/sections", response_model=SectionsResponse)
def sections(session: SessionDep) -> SectionsResponse:
    """Top-level taxonomy sections with their product count and a representative photo."""
    cached = default_sections_cache.get()
    if cached is not None:
        return cached
    rows = (
        session.execute(
            text("select id, key, name from category where parent_id is null order by id")
        )
        .mappings()
        .all()
    )
    counts = {
        row["section_id"]: row["products"]
        for row in session.execute(text(_SECTION_COUNTS_SQL)).mappings()
    }
    images = {
        row["section_id"]: row["image_url"]
        for row in session.execute(text(_SECTION_PHOTOS_SQL)).mappings()
    }
    response = SectionsResponse(
        sections=[
            SectionSummary(
                key=row["key"],
                name=row["name"],
                products=counts[row["id"]],
                image_url=images.get(row["id"]),
            )
            for row in rows
            if counts.get(row["id"], 0) > 0
        ]
    )
    default_sections_cache.set(response)
    return response


@router.get("/products", response_model=ProductsResponse)
def products(
    session: SessionDep,
    section: str | None = None,
    category: str | None = None,
    q: str = "",
    chain: str | None = None,
    chains: str | None = None,
    brand: str | None = None,
    private_label: bool | None = None,
    dietary: str | None = None,
    on_promo: bool | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    near_lat: float | None = None,
    near_lon: float | None = None,
    mode: str | None = None,
    sort: str = "unit_price",
    page: int = 1,
    size: int = 24,
) -> ProductsResponse:
    """A page of the chain products of a section or category, filtered, searched and sorted."""
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise HTTPException(status_code=422, detail=SIZE_ERROR)
    if page < 1:
        raise HTTPException(status_code=422, detail=PAGE_ERROR)
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=SORT_ERROR)
    _validate_price_bounds(min_price, max_price)
    radius = _near_radius(near_lat, near_lon, mode)
    section_id = _category_id(session, section, SECTION_ERROR) if section else None
    category_id = _category_id(session, category, CATEGORY_ERROR) if category else None

    chains_set = _chains_filter(chain, chains)
    if radius is not None:
        nearby = _chains_within_radius(session, near_lat, near_lon, radius)
        chains_set = chains_set & nearby if chains_set else nearby
        if not chains_set:
            return ProductsResponse(items=[], total=0, page=page, size=size)

    brands = brands_for(session)
    params: dict[str, Any] = {}
    conditions = _taxonomy_conditions(section_id, category_id, params)
    query, category_ids = search_params(q, search_forms_for(session), params)
    search = _search_sql(query, category_ids)
    if search is not None:
        conditions.append(search)
    conditions.extend(
        _product_conditions(
            CatalogFilters(
                chains=chains_set,
                brand=(brand or "").strip() or None,
                private_label=private_label,
                dietary=tuple(_split_values(dietary)),
                on_promo=on_promo,
                min_price=min_price,
                max_price=max_price,
            ),
            brands,
            params,
        )
    )
    where = "".join(f" and {condition}" for condition in conditions)
    if query:
        rank = _relevance_rank_sql(("cp.name", "canon.name"), bool(category_ids))
        secondary = _ORDERS["popular"] if sort == "relevance" else _ORDERS[sort]
        order_clause = f"{rank}, {secondary}"
    else:
        order_clause = _ORDERS["popular"] if sort == "relevance" else _ORDERS[sort]
    page_params = {**params, "size": size, "offset": (page - 1) * size}
    rows = (
        session.execute(
            text(
                _CHAIN_ZONE
                + "select "
                + _PRODUCT_COLUMNS
                + _PRODUCT_FROM
                + " where cp.is_active"
                + where
                + " order by "
                + order_clause
                + " limit :size offset :offset"
            ),
            page_params,
        )
        .mappings()
        .all()
    )
    total = session.execute(
        text(_CHAIN_ZONE + "select count(*)" + _PRODUCT_FROM + " where cp.is_active" + where),
        params,
    ).scalar_one()
    return ProductsResponse(
        items=[_to_product(row, brands) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/products/{product_id}", response_model=ProductDetail)
def product(product_id: int, session: SessionDep) -> ProductDetail:
    """One available product and the cheapest other products of its canonical."""
    row = (
        session.execute(
            text(
                _CHAIN_ZONE
                + "select "
                + _PRODUCT_COLUMNS
                + _PRODUCT_FROM
                + " where cp.is_active and cp.id = :product_id"
            ),
            {"product_id": product_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=PRODUCT_ERROR)
    brands = brands_for(session)
    alternatives = []
    if row["canonical_id"] is not None:
        alternatives = [
            _to_product(other, brands)
            for other in session.execute(
                text(
                    _CHAIN_ZONE
                    + "select "
                    + _PRODUCT_COLUMNS
                    + _PRODUCT_FROM
                    + " where cp.is_active and cp.canonical_id = :canonical_id"
                    + " and cp.id <> :product_id"
                    + " order by "
                    + _ORDERS["unit_price"]
                    + " limit :limit"
                ),
                {
                    "canonical_id": row["canonical_id"],
                    "product_id": product_id,
                    "limit": ALTERNATIVES_LIMIT,
                },
            ).mappings()
        ]
    return ProductDetail(**_to_product(row, brands).model_dump(), alternatives=alternatives)
