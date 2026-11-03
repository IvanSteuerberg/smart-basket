"""Health endpoint used by Compose, Caddy and the web placeholder page."""

from typing import Literal

from fastapi import APIRouter, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from smart_basket import __version__
from smart_basket.db import check_database

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"]


@router.get("/health", response_model=Health)
async def health(response: Response) -> Health:
    db_ok = await run_in_threadpool(check_database)
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(
        status="ok" if db_ok else "degraded",
        version=__version__,
        database="ok" if db_ok else "unavailable",
    )
