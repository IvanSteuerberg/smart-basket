"""HTTP API (FastAPI). The API is the only contract for the web and future clients (0008)."""

from smart_basket.api.app import create_app

__all__ = ["create_app"]
