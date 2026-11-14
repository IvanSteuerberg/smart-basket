"""Worker jobs. Ingestion, matching and the BI refresh are placeholders until their deliveries."""

import logging
from datetime import date

from sqlalchemy import text

from smart_basket import stores
from smart_basket.config import get_settings
from smart_basket.db import session_scope
from smart_basket.ingestion import MercadonaAdapter, ingest_catalog
from smart_basket.ingestion.store import log_ingest_summary

log = logging.getLogger(__name__)


def ingest_catalogs() -> None:
    """Collect the Mercadona catalog for every configured warehouse (decision 0006).

    A failing warehouse is logged and skipped so the scheduled chain jobs keep running (NFR-09).
    """
    settings = get_settings()
    for warehouse in settings.mercadona_warehouse_codes:
        adapter = MercadonaAdapter(delay=settings.ingest_delay_seconds)
        try:
            summary = ingest_catalog(adapter, warehouse, data_dir=settings.data_dir)
            log_ingest_summary(summary)
        except Exception:
            log.exception(
                "catalog ingestion failed for warehouse %s; other chains keep running", warehouse
            )
        finally:
            adapter.close()


def import_stores() -> None:
    """Refresh the store locations of the ten chains from OpenStreetMap (decision 0002).

    A failing download is logged and skipped so the other scheduled jobs keep running (NFR-09).
    """
    settings = get_settings()
    try:
        bbox = stores.BoundingBox.parse(settings.stores_bbox)
        with stores.OverpassClient(url=settings.overpass_url) as client:
            observations = stores.fetch_stores(client, bbox)
        summary = stores.import_stores(observations, bbox)
        stores.log_store_summary(summary)
    except Exception:
        log.exception("store import failed; other jobs keep running")


def match_products() -> None:
    """Placeholder: assign new chain products to canonical products (decisions 0004, 0007)."""
    log.info("match_products: matching not implemented yet, nothing to do")


def refresh_bi() -> None:
    """Placeholder: recompute the recent window of the `bi` facts (decision 0007, point 9)."""
    log.info("refresh_bi: BI refresh not implemented yet, nothing to do")


def ensure_price_history_partitions(today: date | None = None) -> None:
    """Create the yearly price_history partitions for this year and the next one."""
    year = (today or date.today()).year
    with session_scope() as session:
        for y in (year, year + 1):
            name = session.execute(
                text("select create_price_history_partition(:y)"), {"y": y}
            ).scalar_one()
            log.info("price_history partition %s ready", name)
