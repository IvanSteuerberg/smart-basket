"""Canonical products catalog (iteration 12, task E6b).

Canonical products represent leaves of the taxonomy with variants, without brand or package size.
The web lists them as cards ("from X €/kg") with the photo and unit price of their cheapest product,
and opens a detail view with all available chain products of that canonical.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.lexicon_cache import search_forms_for
from smart_basket.api.products import (
    _ACTIVE_PRICED_PRODUCT_FROM,
    _CHAIN_ZONE,
    _ORDERS,
    _PROMO_ACTIVE_SQL,
    CATEGORY_ERROR,
    MAX_PAGE_SIZE,
    PAGE_ERROR,
    SECTION_ERROR,
    SIZE_ERROR,
    SORT_ERROR,
    SORTS,
    CatalogFilters,
    ProductOut,
    _category_id,
    _chains_filter,
    _chains_within_radius,
    _fold_sql,
    _near_radius,
    _product_conditions,
    _relevance_rank_sql,
    _split_values,
    _taxonomy_conditions,
    _to_product,
    _unit_price,
    _validate_price_bounds,
    search_params,
)
from smart_basket.brands import brands_for
from smart_basket.db.engine import get_session
from smart_basket.recommender.explanation import decimal_text

router = APIRouter(tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]

CANONICAL_ERROR = "Producto no encontrado."

#: Order by chain coverage first (how many chains sell it), then by product count.
_COVERAGE_ORDER = (
    "coalesce(array_length(ac.chains, 1), 0) desc, cs.product_count desc,"
    " length(canon.name), canon.name, canon.id"
)
#: Popularity: most products first, then the canonical sold by more chains.
_POPULAR_ORDER = (
    "cs.product_count desc, coalesce(array_length(ac.chains, 1), 0) desc, canon.name, canon.id"
)
#: Unit price of the cheapest product of each canonical, null-priced products last.
_UNIT_PRICE_ORDER = (
    "coalesce(cheap.best_price / nullif("
    "cheap.best_quantity * greatest(coalesce(cheap.best_pack_count, 1), 1), 0),"
    " case when cheap.best_unit = 'ud' then cheap.best_price end) asc nulls last,"
    " canon.name, canon.id"
)


class CanonicalSummary(BaseModel):
    id: int
    name: str
    category_key: str
    category_name: str
    image_url: str | None
    from_price: str
    from_unit_price: str
    base_unit: str
    product_count: int
    chains: list[str]
    #: Only concrete products are bought in this category (shades): no generic "any" line.
    exact_only: bool


class CanonicalsResponse(BaseModel):
    items: list[CanonicalSummary]
    total: int
    page: int
    size: int


class CanonicalDetail(CanonicalSummary):
    products: list[ProductOut]


#: The joins that give each active product its effective category (the canonical's one).
_PRODUCT_CATEGORY_JOINS = """
left join canonical_product canon on canon.id = cp.canonical_id
left join chain_category ccat on ccat.id = cp.chain_category_id
join category ec on ec.id = coalesce(canon.category_id, ccat.category_id)
"""

_CANONICAL_DETAIL_SQL = (
    _CHAIN_ZONE
    + """
select
    cp.id, cp.name, cp.packaging, cp.image_url, cp.base_quantity, cp.base_unit,
    cp.pack_count, cp.dietary_tags,
    cp.chain_id, ch.code as chain_code, ch.name as chain_name, pc.price,
    cp.canonical_id, canon.name as canonical_name,
    ec.id as category_id, ec.key as category_key, ec.name as category_name,
    ec.exact_only,
    ({promo}) as on_promo
"""
    + _ACTIVE_PRICED_PRODUCT_FROM
    + """
join canonical_product canon on canon.id = cp.canonical_id
join category ec on ec.id = canon.category_id
where cp.is_active and cp.canonical_id = :canonical_id and cp.base_quantity is not null
order by
"""
    + _ORDERS["unit_price"]
).replace("{promo}", _PROMO_ACTIVE_SQL)


def _canonicals_sql(
    product_where: str,
    where_sql: str,
    order_clause: str,
) -> str:
    return (
        _CHAIN_ZONE
        + f""",
active_products as (
    select
        cp.id as product_id,
        cp.canonical_id,
        cp.name as product_name,
        cp.image_url,
        cp.base_unit,
        cp.base_quantity,
        cp.pack_count,
        pc.price,
        ch.code as chain_code,
        row_number() over (
            partition by cp.canonical_id
            order by {_ORDERS["unit_price"]}
        ) as rn
    {_ACTIVE_PRICED_PRODUCT_FROM}
    {_PRODUCT_CATEGORY_JOINS}
    where cp.is_active
      and cp.canonical_id is not null
      and cp.base_quantity is not null
      {product_where}
),
canonical_summary as (
    select
        canonical_id,
        min(price) as from_price,
        count(*) as product_count
    from active_products
    group by canonical_id
),
cheapest_product as (
    select
        canonical_id,
        image_url,
        price as best_price,
        base_quantity as best_quantity,
        base_unit as best_unit,
        pack_count as best_pack_count
    from active_products
    where rn = 1
),
all_chains as (
    select
        cp.canonical_id,
        array_agg(distinct ch.code order by ch.code) as chains
    {_ACTIVE_PRICED_PRODUCT_FROM}
    where cp.is_active
      and cp.canonical_id is not null
      and cp.base_quantity is not null
    group by cp.canonical_id
)
select
    canon.id,
    canon.name,
    ec.key as category_key,
    ec.name as category_name,
    ec.exact_only,
    cheap.image_url,
    cs.from_price,
    cheap.best_price,
    cheap.best_quantity,
    cheap.best_unit,
    cheap.best_pack_count,
    cs.product_count,
    ac.chains
from canonical_product canon
join category ec on ec.id = canon.category_id
join canonical_summary cs on cs.canonical_id = canon.id
join cheapest_product cheap on cheap.canonical_id = canon.id
join all_chains ac on ac.canonical_id = canon.id
{where_sql}
order by {order_clause}
limit :size offset :offset
"""
    )


def _canonicals_count_sql(product_where: str, where_sql: str) -> str:
    return (
        _CHAIN_ZONE
        + f""",
active_products as (
    select
        cp.canonical_id,
        cp.name as product_name
    {_ACTIVE_PRICED_PRODUCT_FROM}
    {_PRODUCT_CATEGORY_JOINS}
    where cp.is_active
      and cp.canonical_id is not null
      and cp.base_quantity is not null
      {product_where}
),
canonical_summary as (
    select distinct canonical_id
    from active_products
)
select count(*)
from canonical_product canon
join category ec on ec.id = canon.category_id
join canonical_summary cs on cs.canonical_id = canon.id
{where_sql}
"""
    )


def _canonicals_order(sort: str, has_query: bool, has_categories: bool) -> str:
    """Rank by query relevance first when searching, then by the requested order."""
    rank = ""
    if has_query:
        rank = _relevance_rank_sql(("canon.name",), has_categories) + ", "
    if sort == "relevance":
        return rank + _COVERAGE_ORDER
    if sort == "popular":
        return rank + _POPULAR_ORDER
    if sort == "unit_price":
        return rank + _UNIT_PRICE_ORDER
    if sort == "price":
        return rank + "cs.from_price asc, canon.name, canon.id"
    return rank + "canon.name, canon.id"


@router.get("/canonicals", response_model=CanonicalsResponse)
def canonicals(
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
    sort: str = "relevance",
    page: int = 1,
    size: int = 24,
) -> CanonicalsResponse:
    """A page of canonical products, filtered by taxonomy, chain, brand or text, with prices."""
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
            return CanonicalsResponse(items=[], total=0, page=page, size=size)

    brands = brands_for(session)
    params: dict[str, Any] = {}
    where_parts: list[str] = _taxonomy_conditions(section_id, category_id, params)

    query, category_ids = search_params(q, search_forms_for(session), params)
    if query:
        canon_name_match = " and ".join(
            f"{_fold_sql('canon.name')} ~ :q_word_{i}" for i in range(len(query))
        )
        product_name_match = " and ".join(
            f"{_fold_sql('ap.product_name')} ~ :q_word_{i}" for i in range(len(query))
        )
        product_match = (
            "canon.id in (select ap.canonical_id from active_products ap "
            f"where {product_name_match})"
        )
        if category_ids:
            cat_match = (
                "ec.id in (select descendant_id from category_closure "
                "where ancestor_id = any(:q_categories))"
            )
            where_parts.append(f"(({canon_name_match}) or ({product_match}) or ({cat_match}))")
        else:
            where_parts.append(f"(({canon_name_match}) or ({product_match}))")

    product_where = "".join(
        f" and {condition}"
        for condition in _product_conditions(
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
    where_sql = (" where " + " and ".join(where_parts)) if where_parts else ""
    order_clause = _canonicals_order(sort, bool(query), bool(category_ids))
    page_params = {**params, "size": size, "offset": (page - 1) * size}

    rows = (
        session.execute(text(_canonicals_sql(product_where, where_sql, order_clause)), page_params)
        .mappings()
        .all()
    )
    total = session.execute(
        text(_canonicals_count_sql(product_where, where_sql)), params
    ).scalar_one()

    items = []
    for row in rows:
        unit_price = _unit_price(
            row["best_price"], row["best_quantity"], row["best_unit"], row["best_pack_count"]
        )
        assert unit_price is not None
        assert row["best_unit"] is not None
        items.append(
            CanonicalSummary(
                id=row["id"],
                name=row["name"],
                category_key=row["category_key"],
                category_name=row["category_name"],
                image_url=row["image_url"],
                from_price=decimal_text(row["from_price"]),
                from_unit_price=unit_price,
                base_unit=row["best_unit"],
                product_count=row["product_count"],
                chains=list(row["chains"]),
                exact_only=row["exact_only"],
            )
        )
    return CanonicalsResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )


@router.get("/canonicals/{canonical_id}", response_model=CanonicalDetail)
def canonical(canonical_id: int, session: SessionDep) -> CanonicalDetail:
    """One canonical product with its active priced chain products sorted by unit price."""
    rows = (
        session.execute(text(_CANONICAL_DETAIL_SQL), {"canonical_id": canonical_id})
        .mappings()
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail=CANONICAL_ERROR)

    best = rows[0]
    unit_price = _unit_price(
        best["price"], best["base_quantity"], best["base_unit"], best["pack_count"]
    )
    if unit_price is None or best["base_unit"] is None:
        raise HTTPException(status_code=404, detail=CANONICAL_ERROR)

    brands = brands_for(session)
    products = [_to_product(row, brands) for row in rows]
    return CanonicalDetail(
        id=canonical_id,
        name=best["canonical_name"],
        category_key=best["category_key"],
        category_name=best["category_name"],
        image_url=best["image_url"],
        from_price=decimal_text(min(row["price"] for row in rows)),
        from_unit_price=unit_price,
        base_unit=best["base_unit"],
        product_count=len(rows),
        chains=sorted({row["chain_code"] for row in rows}),
        exact_only=best["exact_only"],
        products=products,
    )
