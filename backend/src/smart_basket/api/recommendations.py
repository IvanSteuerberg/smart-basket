"""Recommendation endpoint (FR-13): the list, the origin and the preferences in, a basket out."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from smart_basket.config import get_settings
from smart_basket.db import get_session
from smart_basket.optimizer import PriorityMode, Unit
from smart_basket.recommender import NoCandidateStores, RecommendationQuery, recommend
from smart_basket.recommender.catalog import Item, UnknownProduct, variant_keys
from smart_basket.recommender.service import (
    BasketCalculationError,
    RecommendationResponse,
    VagueLine,
)
from smart_basket.routing import GeoPoint, RoutingEngine, RoutingError, TravelMode, ValhallaClient

router = APIRouter(tags=["recommendations"])
logger = logging.getLogger(__name__)

NO_STORES = "No hay tiendas con precios cerca de este punto."
ROUTING_FAILED = "No se ha podido calcular la ruta. Inténtalo de nuevo en unos minutos."
BASKET_FAILED = "No se ha podido calcular la cesta con esta lista."


class ItemRequest(BaseModel):
    text: str = Field(min_length=1)
    #: Exactly one of a generic `category_key` and a concrete `product_id`.
    category_key: str | None = Field(default=None, min_length=1)
    product_id: int | None = Field(default=None, gt=0)
    accept: Literal["exact", "equivalent"] = "equivalent"
    #: Variant keys of `variants_es.json`; when absent they are read from `text`.
    variants: list[str] | None = None
    quantity: Decimal = Field(gt=0)
    unit: Unit
    brand: str | None = None
    private_label_ok: bool = True

    @model_validator(mode="after")
    def _check_line(self) -> ItemRequest:
        if (self.category_key is None) == (self.product_id is None):
            raise ValueError("exactly one of category_key and product_id is required")
        if self.category_key is not None and self.accept == "exact":
            raise ValueError("a generic category line only accepts equivalent products")
        if self.product_id is not None and self.unit is not Unit.UD:
            raise ValueError("a concrete product line counts units")
        if self.variants is not None:
            unknown = sorted(set(self.variants) - variant_keys())
            if unknown:
                raise ValueError(f"unknown variant key {unknown[0]!r}")
        return self


class OriginRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RecommendationRequest(BaseModel):
    items: list[ItemRequest] = Field(min_length=1)
    origin: OriginRequest
    mode: TravelMode
    max_stores: int = Field(ge=1, le=3)
    priority_mode: PriorityMode = PriorityMode.BALANCED
    return_to_origin: bool = True
    degraded: bool = False
    chains: list[str] | None = None


def get_routing_engine() -> Iterator[RoutingEngine]:
    settings = get_settings()
    client = ValhallaClient(settings.valhalla_url, timeout=settings.routing_timeout_seconds)
    try:
        yield client
    finally:
        client.close()


def get_today() -> date:
    """Today in the application timezone; replaced in tests to pin the shopping date."""
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


@router.post("/recommendations", response_model=RecommendationResponse)
def create_recommendation(
    request: RecommendationRequest,
    session: Annotated[Session, Depends(get_session)],
    routing: Annotated[RoutingEngine, Depends(get_routing_engine)],
    today: Annotated[date, Depends(get_today)],
) -> RecommendationResponse:
    query = RecommendationQuery(
        items=tuple(
            Item(
                text=item.text,
                category_key=item.category_key,
                product_id=item.product_id,
                accept=item.accept,
                variants=tuple(item.variants) if item.variants is not None else None,
                quantity=item.quantity,
                unit=item.unit,
                brand=item.brand,
                private_label_ok=item.private_label_ok,
            )
            for item in request.items
        ),
        origin=GeoPoint(request.origin.lat, request.origin.lon),
        mode=request.mode,
        max_stores=request.max_stores,
        priority_mode=request.priority_mode,
        return_to_origin=request.return_to_origin,
        degraded=request.degraded,
        chains=tuple(request.chains or ()),
        payload=request.model_dump(mode="json"),
    )
    try:
        return recommend(session, query, routing, today, get_settings())
    except VagueLine as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "VAGUE_LINE",
                "line_id": exc.line_id,
                "category_key": exc.category_key,
                "message": exc.message,
            },
        ) from None
    except UnknownProduct:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Producto desconocido."
        ) from None
    except NoCandidateStores:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=NO_STORES
        ) from None
    except RoutingError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ROUTING_FAILED
        ) from None
    except BasketCalculationError as exc:
        # The message describes the basket, never the origin.
        logger.warning("basket calculation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=BASKET_FAILED
        ) from None
