"""Recommendation endpoint (FR-13): the list, the origin and the preferences in, a basket out."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from smart_basket.config import get_settings
from smart_basket.db import get_session
from smart_basket.optimizer import PriorityMode, Unit
from smart_basket.recommender import NoCandidateStores, RecommendationQuery, recommend
from smart_basket.recommender.catalog import Item
from smart_basket.routing import GeoPoint, RoutingEngine, RoutingError, TravelMode, ValhallaClient

router = APIRouter(tags=["recommendations"])

NO_STORES = "No hay tiendas con precios cerca de este punto."
ROUTING_FAILED = "No se ha podido calcular la ruta. Inténtalo de nuevo en unos minutos."


class ItemRequest(BaseModel):
    text: str = Field(min_length=1)
    category_key: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: Unit
    brand: str | None = None
    private_label_ok: bool = True


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


class LineResponse(BaseModel):
    text: str
    product_name: str
    packs: int
    quantity_bought: str
    cost: str


class StoreResponse(BaseModel):
    store_id: int
    name: str
    chain: str
    lat: float
    lon: float
    position: int
    lines: list[LineResponse]
    subtotal: str


class StopResponse(BaseModel):
    store_id: int
    name: str
    cost: str
    extra_minutes: str
    exceeds_max_stores: bool


class MissingResponse(BaseModel):
    text: str
    reason: Literal["not_available", "separate_stop", "unreachable"]
    stop: StopResponse | None = None


class RecommendationResponse(BaseModel):
    id: str
    data_as_of: str
    engine_version: str
    stores: list[StoreResponse]
    total_cost: str
    minutes: str
    missing: list[MissingResponse]
    route: list[list[float]]
    explanation: str
    degraded: bool


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
) -> dict:
    query = RecommendationQuery(
        items=tuple(
            Item(
                text=item.text,
                category_key=item.category_key,
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
        payload=request.model_dump(mode="json"),
    )
    try:
        return recommend(session, query, routing, today, get_settings())
    except NoCandidateStores:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=NO_STORES
        ) from None
    except RoutingError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ROUTING_FAILED
        ) from None
