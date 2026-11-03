"""FastAPI application factory."""

from fastapi import FastAPI

from smart_basket import __version__
from smart_basket.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Smart Basket API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(health_router, prefix="/api")
    return app


app = create_app()
