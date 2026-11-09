"""Worker jobs. Ingestion, matching and the BI refresh are placeholders until their deliveries."""

import logging
from datetime import date

from sqlalchemy import text

from smart_basket.config import get_settings
from smart_basket.db import session_scope
from smart_basket.ingestion import MercadonaAdapter, ingest_catalog

log = logging.getLogger(__name__)


def ingest_catalogs() -> None:
    """Collect the Mercadona catalog for every configured warehouse (decision 0006).

    A failing warehouse is logged and skipped so the scheduled chain jobs keep running (NFR-09).
    """
    settings = get_settings()
    warehouses = [code.strip() for code in settings.mercadona_warehouses.split(",") if code.strip()]
    for warehouse in warehouses:
        adapter = MercadonaAdapter(delay=settings.ingest_delay_seconds)
        try:
            summary = ingest_catalog(adapter, warehouse, data_dir=settings.data_dir)
            log.info(
                "catalog run %s for %s/%s: %s, %s products, %s price changes, %s errors",
                summary.run_id,
                summary.chain_code,
                summary.zone_code,
                summary.status,
                summary.products_seen,
                summary.prices_changed,
                len(summary.errors),
            )
        except Exception:
            log.exception(
                "catalog ingestion failed for warehouse %s; other chains keep running", warehouse
            )
        finally:
            adapter.close()


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
