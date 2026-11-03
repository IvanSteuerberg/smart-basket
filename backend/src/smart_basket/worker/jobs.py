"""Worker jobs. Ingestion, matching and the BI refresh are placeholders until their deliveries."""

import logging
from datetime import date

from sqlalchemy import text

from smart_basket.db import session_scope

log = logging.getLogger(__name__)


def ingest_catalogs() -> None:
    """Placeholder: collect catalogs, prices and promotions per chain (decision 0006)."""
    log.info("ingest_catalogs: no chain adapters yet, nothing to do")


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
