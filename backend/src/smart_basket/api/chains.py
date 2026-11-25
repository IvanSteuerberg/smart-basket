"""Chains the shopper can browse (iteration 17, Wave 0).

Only a chain with at least one active store has products to shop in Leon, so the web lists just
those: the number of active stores, the priced products in the chain's chosen zone and the date
of the latest price. A chain without active stores is hidden even if it still has priced rows,
which is what happens to Carrefour before its OpenStreetMap stores are loaded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.api.products import _CHAIN_ZONE
from smart_basket.db.engine import get_session

router = APIRouter(tags=["catalog"])

SessionDep = Annotated[Session, Depends(get_session)]

#: Chains with at least one active store; counts follow `_ACTIVE_PRICED_PRODUCT_FROM` in a left
#: join so a chain with stores but no priced products still appears with zero products.
_ACTIVE_CHAINS_SQL = (
    _CHAIN_ZONE
    + """
select
    ch.code,
    ch.name,
    count(distinct s.id) as store_count,
    count(distinct cp.id) filter (
        where cpz.chain_product_id is not null and pc.chain_product_id is not null
    ) as product_count,
    max(pc.valid_from) as last_price_at
from chain ch
join store s on s.chain_id = ch.id and s.is_active
join chosen cz on cz.chain_id = ch.id
left join chain_product cp on cp.chain_id = ch.id and cp.is_active
left join chain_product_zone cpz
    on cpz.chain_product_id = cp.id and cpz.zone_id = cz.zone_id and cpz.is_available
left join price_current pc
    on cpz.chain_product_id is not null
    and pc.chain_product_id = cp.id
    and pc.zone_id = cz.zone_id
group by ch.id, ch.code, ch.name
order by ch.name
"""
)


class ChainSummary(BaseModel):
    code: str
    name: str
    store_count: int
    product_count: int
    last_price_at: datetime | None


class ChainsResponse(BaseModel):
    chains: list[ChainSummary]


@router.get("/chains", response_model=ChainsResponse)
def chains(session: SessionDep) -> ChainsResponse:
    """Chains with at least one active store, ordered by name."""
    rows = session.execute(text(_ACTIVE_CHAINS_SQL)).mappings().all()
    return ChainsResponse(
        chains=[
            ChainSummary(
                code=row["code"],
                name=row["name"],
                store_count=row["store_count"],
                product_count=row["product_count"],
                last_price_at=row["last_price_at"],
            )
            for row in rows
        ]
    )
