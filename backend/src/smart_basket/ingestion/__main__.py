"""`smart-basket-ingest`: crawl one chain manually, optionally without touching the database."""

import argparse
import logging

from smart_basket.config import get_settings
from smart_basket.ingestion.base import collect
from smart_basket.ingestion.mercadona import MercadonaAdapter
from smart_basket.ingestion.store import ingest_catalog

log = logging.getLogger("smart_basket.ingestion")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smart-basket-ingest")
    parser.add_argument("chain", choices=["mercadona"])
    parser.add_argument(
        "--warehouse",
        help="warehouse code; defaults to MERCADONA_WAREHOUSES",
    )
    parser.add_argument(
        "--max-categories",
        type=int,
        default=None,
        help="crawl only the first N level 2 categories (the run is then incomplete)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="crawl and parse without touching the database",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    warehouses = (
        [args.warehouse]
        if args.warehouse
        else [code.strip() for code in settings.mercadona_warehouses.split(",") if code.strip()]
    )
    adapter = MercadonaAdapter(delay=settings.ingest_delay_seconds)
    try:
        for warehouse in warehouses:
            if args.dry_run:
                result = collect(adapter, warehouse, max_categories=args.max_categories)
                print(
                    f"{warehouse}: categories={len(result.categories)} "
                    f"products={len(result.products)} responses={len(result.raw)} "
                    f"errors={len(result.errors)} status={result.status} "
                    f"complete={result.complete}"
                )
                if result.status == "failed":
                    return 1
                continue
            summary = ingest_catalog(
                adapter,
                warehouse,
                data_dir=settings.data_dir,
                max_categories=args.max_categories,
            )
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
            if summary.status == "failed":
                return 1
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
