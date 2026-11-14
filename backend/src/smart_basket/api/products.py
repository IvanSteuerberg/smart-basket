"""Supermarket-style catalog: sections, products and product detail (iteration 12, task E4).

The web browses the chain products by taxonomy section, searches them by folded text and opens a
product with its alternatives. Prices are read from the zone of each chain's active stores in
León, so a product is listed only when that zone sells it with a current price. Everything here
is read-only and answerable in a couple of queries.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.lexicon_cache import search_forms_for
from smart_basket.brands import Brands, brands_for
from smart_basket.db.engine import get_session
from smart_basket.preprocessor.rules_es import CONNECTORS
from smart_basket.preprocessor.text import tokenize
from smart_basket.recommender.explanation import decimal_text

router = APIRouter(tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]

#: Unit prices keep the four decimals of `price_current.price_per_unit`.
UNIT_PRICE_QUANTUM = Decimal("0.0001")
SORTS = ("unit_price", "price", "name")
MAX_PAGE_SIZE = 60
ALTERNATIVES_LIMIT = 12

SIZE_ERROR = "El tamaño de la página debe estar entre 1 y 60."
PAGE_ERROR = "La página debe ser al menos 1."
SORT_ERROR = "El orden debe ser unit_price, price o name."
SECTION_ERROR = "La sección no existe."
CATEGORY_ERROR = "La categoría no existe."
PRODUCT_ERROR = "El producto no existe o no está disponible."

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

#: A listed product: active and available in its chain's zone, with a current price.
_PRODUCT_COLUMNS = """
    cp.id, cp.name, cp.packaging, cp.image_url, cp.base_quantity, cp.base_unit,
    cp.chain_id, ch.name as chain_name, pc.price,
    cp.canonical_id, canon.name as canonical_name,
    ec.id as category_id, ec.key as category_key, ec.name as category_name
"""
_PRODUCT_FROM = """
from chain_product cp
join chain ch on ch.id = cp.chain_id
join chosen cz on cz.chain_id = cp.chain_id
join chain_product_zone cpz
    on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
join price_current pc
    on pc.chain_product_id = cp.id and pc.zone_id = cz.zone_id
left join canonical_product canon on canon.id = cp.canonical_id
left join chain_category ccat on ccat.id = cp.chain_category_id
join category ec on ec.id = coalesce(canon.category_id, ccat.category_id)
"""

_ORDERS = {
    "unit_price": "(cp.base_quantity is null), pc.price / cp.base_quantity, cp.name, cp.id",
    "price": "pc.price, cp.name, cp.id",
    "name": "cp.name, cp.id",
}

#: The product name folded the way `smart_basket.preprocessor.text.fold` does.
_FOLDED_NAME = "translate(lower(cp.name), 'áàäâãéèëêíìïîóòöôõúùüûñç', 'aaaaaeeeeiiiiooooouuuunc')"

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

_SECTION_PHOTOS_SQL = (
    _CHAIN_ZONE
    + """
select cl.ancestor_id as section_id, cp.id, cp.image_url, cp.canonical_id,
       coalesce(canon.category_id, ccat.category_id) as node_id
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
order by cl.ancestor_id, cp.id
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


def _word_pattern(word: str) -> str:
    """Whole-word pattern for `word`, tolerating a plural -s or -es on either side."""
    variants = {word, word + "s", word + "es"}
    if word.endswith("s") and len(word) > 1:
        variants.add(word[:-1])
    if word.endswith("es") and len(word) > 2:
        variants.add(word[:-2])
    body = "|".join(
        _regex_escape(variant) for variant in sorted(variants, key=len, reverse=True) if variant
    )
    return rf"(^|[^a-z0-9])({body})([^a-z0-9]|$)"


def _query_words(q: str) -> tuple[str, ...]:
    """Folded content tokens of `q`; connectors such as "de" carry no product meaning."""
    return tuple(
        token.key
        for token in tokenize(q)
        if token.kind in ("word", "num") and token.key not in CONNECTORS
    )


def _search_sql(q: str, forms: Mapping[int, Iterable[str]], params: dict[str, Any]) -> str | None:
    """Every word in the product name, or a match of `q` against the category's forms."""
    query = _query_words(q)
    if not query:
        return None
    name_parts = []
    for index, word in enumerate(query):
        key = f"q_word_{index}"
        params[key] = _word_pattern(word)
        name_parts.append(f"{_FOLDED_NAME} ~ :{key}")
    normalized = " ".join(query)
    category_ids = sorted(
        category_id
        for category_id, category_forms in forms.items()
        if any(form.strip() == normalized for form in category_forms)
    )
    if not category_ids:
        return f"({' and '.join(name_parts)})"
    params["q_categories"] = category_ids
    return f"(({' and '.join(name_parts)}) or ec.id = any(:q_categories))"


def _filters(
    section_id: int | None,
    category_id: int | None,
    q: str,
    forms: Mapping[int, Iterable[str]],
    params: dict[str, Any],
) -> str:
    conditions = []
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
    search = _search_sql(q, forms, params)
    if search is not None:
        conditions.append(search)
    return "".join(f" and {condition}" for condition in conditions)


def _category_id(session: Session, key: str, error: str) -> int:
    category_id = session.execute(
        text("select id from category where key = :key"), {"key": key}
    ).scalar_one_or_none()
    if category_id is None:
        raise HTTPException(status_code=422, detail=error)
    return category_id


def _unit_price(price: Decimal, quantity: Decimal | None, unit: str | None) -> str | None:
    if quantity is None:
        return decimal_text(price) if unit == "ud" else None
    return decimal_text((price / quantity).quantize(UNIT_PRICE_QUANTUM, rounding=ROUND_HALF_UP))


def _to_product(row: Mapping[str, Any], brands: Brands) -> ProductOut:
    canonical = None
    if row["canonical_id"] is not None:
        canonical = CanonicalOut(
            id=row["canonical_id"],
            name=row["canonical_name"],
            category_key=row["category_key"],
            category_name=row["category_name"],
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
        unit_price=_unit_price(row["price"], row["base_quantity"], row["base_unit"]),
        base_unit=row["base_unit"],
        base_quantity=(
            decimal_text(row["base_quantity"]) if row["base_quantity"] is not None else None
        ),
        canonical=canonical,
    )


def _section_images(rows: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """Lowest-id photo of the most common canonical (or leaf) of each section."""
    groups: dict[int, dict[int, list[tuple[int, str]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = row["canonical_id"] if row["canonical_id"] is not None else row["node_id"]
        groups[row["section_id"]][key].append((row["id"], row["image_url"]))
    images = {}
    for section_id, by_key in groups.items():
        # Rows arrive ordered by product id, so the first of each group is its lowest id.
        best = max(by_key, key=lambda key: (len(by_key[key]), -by_key[key][0][0]))
        images[section_id] = by_key[best][0][1]
    return images


# Routes --------------------------------------------------------------------


@router.get("/sections", response_model=SectionsResponse)
def sections(session: SessionDep) -> SectionsResponse:
    """Top-level taxonomy sections with their product count and a representative photo."""
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
    images = _section_images(session.execute(text(_SECTION_PHOTOS_SQL)).mappings())
    return SectionsResponse(
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


@router.get("/products", response_model=ProductsResponse)
def products(
    session: SessionDep,
    section: str | None = None,
    category: str | None = None,
    q: str = "",
    sort: str = "unit_price",
    page: int = 1,
    size: int = 24,
) -> ProductsResponse:
    """A page of the chain products of a section or category, searched and sorted."""
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise HTTPException(status_code=422, detail=SIZE_ERROR)
    if page < 1:
        raise HTTPException(status_code=422, detail=PAGE_ERROR)
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=SORT_ERROR)
    section_id = _category_id(session, section, SECTION_ERROR) if section else None
    category_id = _category_id(session, category, CATEGORY_ERROR) if category else None
    params: dict[str, Any] = {}
    where = _filters(section_id, category_id, q, search_forms_for(session), params)
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
                + _ORDERS[sort]
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
    brands = brands_for(session)
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
