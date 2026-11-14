"""Catalog ingestion: one adapter per chain and shared persistence (decisions 0006, 0007)."""

from smart_basket.ingestion.backfill import ImageBackfillSummary, backfill_images
from smart_basket.ingestion.base import (
    CategoryObservation,
    ChainAdapter,
    CrawlError,
    CrawlResult,
    Observation,
    ProductObservation,
    RawResponse,
    collect,
)
from smart_basket.ingestion.http import Fetcher, FetchError
from smart_basket.ingestion.mercadona import MercadonaAdapter
from smart_basket.ingestion.store import IngestSetupError, IngestSummary, ingest_catalog

__all__ = [
    "CategoryObservation",
    "ChainAdapter",
    "CrawlError",
    "CrawlResult",
    "FetchError",
    "Fetcher",
    "ImageBackfillSummary",
    "IngestSetupError",
    "IngestSummary",
    "MercadonaAdapter",
    "Observation",
    "ProductObservation",
    "RawResponse",
    "backfill_images",
    "collect",
    "ingest_catalog",
]
