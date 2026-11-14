"""Canonical products catalog (iteration 12, task E6b).

Canonical products represent leaves of the taxonomy with variants, without brand or package size.
The web lists them as cards ("from X €/kg") with the photo and unit price of their cheapest product,
and opens a detail view with all available chain products of that canonical.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.lexicon_cache import search_forms_for
from smart_basket.api.products import (
    _CHAIN_ZONE,
    _ORDERS,
    CATEGORY_ERROR,
    MAX_PAGE_SIZE,
    PAGE_ERROR,
    SECTION_ERROR,
    SIZE_ERROR,
    ProductOut,
    _category_id,
    _fold_sql,
    _relevance_sql,
    _to_product,
    _unit_price,
    search_params,
)
from smart_basket.brands import brands_for
from smart_basket.db.engine import get_session
from smart_basket.recommender.explanation import decimal_text

router = APIRouter(tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]

CANONICAL_ERROR = "Producto no encontrado."


class CanonicalSummary(BaseModel):
    id: int
    name: str
    category_key: str
    category_name: str
    image_url: str | None
    from_price: str
    from_unit_price: str | None
    base_unit: str | None
    product_count: int
    chains: list[str]


class CanonicalsResponse(BaseModel):
    items: list[CanonicalSummary]
    total: int
    page: int
    size: int


class CanonicalDetail(CanonicalSummary):
    products: list[ProductOut]


_CANONICAL_DETAIL_SQL = (
    _CHAIN_ZONE
    + """
select
    cp.id, cp.name, cp.packaging, cp.image_url, cp.base_quantity, cp.base_unit,
    cp.chain_id, ch.code as chain_code, ch.name as chain_name, pc.price,
    cp.canonical_id, canon.name as canonical_name,
    ec.id as category_id, ec.key as category_key, ec.name as category_name
from chain_product cp
join chain ch on ch.id = cp.chain_id
join chosen cz on cz.chain_id = cp.chain_id
join chain_product_zone cpz
    on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
join price_current pc
    on pc.chain_product_id = cp.id and pc.zone_id = cz.zone_id
join canonical_product canon on canon.id = cp.canonical_id
join category ec on ec.id = canon.category_id
where cp.is_active and cp.canonical_id = :canonical_id
order by
"""
    + _ORDERS["unit_price"]
)


def _canonicals_sql(
    chain_filter: bool,
    where_sql: str,
    order_clause: str,
) -> str:
    chain_cond = " and ch.code = :chain" if chain_filter else ""
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
        pc.price,
        ch.code as chain_code,
        row_number() over (
            partition by cp.canonical_id
            order by
                (cp.base_quantity is null and cp.base_unit is distinct from 'ud'),
                coalesce(
                    pc.price / nullif(cp.base_quantity, 0),
                    case when cp.base_unit = 'ud' then pc.price end
                ),
                cp.name,
                cp.id
        ) as rn
    from chain_product cp
    join chain ch on ch.id = cp.chain_id
    join chosen cz on cz.chain_id = cp.chain_id
    join chain_product_zone cpz
        on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
    join price_current pc
        on pc.chain_product_id = cp.id and pc.zone_id = cz.zone_id
    where cp.is_active
      and cp.canonical_id is not null
      {chain_cond}
),
canonical_summary as (
    select
        canonical_id,
        min(price) as from_price,
        count(*) as product_count,
        array_agg(distinct chain_code order by chain_code) as chains
    from active_products
    group by canonical_id
),
cheapest_product as (
    select
        canonical_id,
        image_url,
        price as best_price,
        base_quantity as best_quantity,
        base_unit as best_unit
    from active_products
    where rn = 1
)
select
    canon.id,
    canon.name,
    ec.key as category_key,
    ec.name as category_name,
    cp.image_url,
    cs.from_price,
    cp.best_price,
    cp.best_quantity,
    cp.best_unit,
    cs.product_count,
    cs.chains
from canonical_product canon
join category ec on ec.id = canon.category_id
join canonical_summary cs on cs.canonical_id = canon.id
join cheapest_product cp on cp.canonical_id = canon.id
{where_sql}
order by {order_clause}
limit :size offset :offset
"""
    )


def _canonicals_count_sql(chain_filter: bool, where_sql: str) -> str:
    chain_cond = " and ch.code = :chain" if chain_filter else ""
    return (
        _CHAIN_ZONE
        + f""",
active_products as (
    select
        cp.canonical_id,
        cp.name as product_name
    from chain_product cp
    join chain ch on ch.id = cp.chain_id
    join chosen cz on cz.chain_id = cp.chain_id
    join chain_product_zone cpz
        on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
    join price_current pc
        on pc.chain_product_id = cp.id and pc.zone_id = cz.zone_id
    where cp.is_active
      and cp.canonical_id is not null
      {chain_cond}
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


@router.get("/canonicals", response_model=CanonicalsResponse)
def canonicals(
    session: SessionDep,
    section: str | None = None,
    category: str | None = None,
    q: str = "",
    chain: str | None = None,
    page: int = 1,
    size: int = 24,
) -> CanonicalsResponse:
    """A page of canonical products, filtered by taxonomy, chain or text, with lowest prices."""
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise HTTPException(status_code=422, detail=SIZE_ERROR)
    if page < 1:
        raise HTTPException(status_code=422, detail=PAGE_ERROR)

    section_id = _category_id(session, section, SECTION_ERROR) if section else None
    category_id = _category_id(session, category, CATEGORY_ERROR) if category else None

    params: dict[str, Any] = {}
    where_parts: list[str] = []

    if chain:
        params["chain"] = chain

    if section_id is not None:
        params["section_id"] = section_id
        where_parts.append(
            "ec.id in (select descendant_id from category_closure where ancestor_id = :section_id)"
        )
    if category_id is not None:
        params["category_id"] = category_id
        where_parts.append(
            "ec.id in (select descendant_id from category_closure where ancestor_id = :category_id)"
        )

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
        relevance = _relevance_sql("canon.name", bool(category_ids))
        order_clause = f"{relevance}, ec.name, canon.name, canon.id"
    else:
        order_clause = "ec.name, canon.name, canon.id"

    where_sql = (" where " + " and ".join(where_parts)) if where_parts else ""
    page_params = {**params, "size": size, "offset": (page - 1) * size}

    sql = _canonicals_sql(chain_filter=bool(chain), where_sql=where_sql, order_clause=order_clause)
    rows = session.execute(text(sql), page_params).mappings().all()

    count_sql = _canonicals_count_sql(chain_filter=bool(chain), where_sql=where_sql)
    total = session.execute(text(count_sql), params).scalar_one()

    items = [
        CanonicalSummary(
            id=row["id"],
            name=row["name"],
            category_key=row["category_key"],
            category_name=row["category_name"],
            image_url=row["image_url"],
            from_price=decimal_text(row["from_price"]),
            from_unit_price=_unit_price(row["best_price"], row["best_quantity"], row["best_unit"]),
            base_unit=row["best_unit"],
            product_count=row["product_count"],
            chains=list(row["chains"]),
        )
        for row in rows
    ]
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
    brands = brands_for(session)
    products = [_to_product(row, brands) for row in rows]
    return CanonicalDetail(
        id=canonical_id,
        name=best["canonical_name"],
        category_key=best["category_key"],
        category_name=best["category_name"],
        image_url=best["image_url"],
        from_price=decimal_text(min(row["price"] for row in rows)),
        from_unit_price=_unit_price(best["price"], best["base_quantity"], best["base_unit"]),
        base_unit=best["base_unit"],
        product_count=len(rows),
        chains=sorted({row["chain_code"] for row in rows}),
        products=products,
    )
