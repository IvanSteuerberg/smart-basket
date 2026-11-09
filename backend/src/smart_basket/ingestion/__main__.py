"""`smart-basket-ingest`: crawl one chain manually, optionally without touching the database."""

import argparse
import logging
import sys

from smart_basket.config import get_settings
from smart_basket.ingestion.base import collect
from smart_basket.ingestion.mercadona import MercadonaAdapter
from smart_basket.ingestion.store import IngestSetupError, ingest_catalog, log_ingest_summary

log = logging.getLogger("smart_basket.ingestion")


def _non_negative_int(value: str) -> int:
    """Argparse type for counts that cannot be negative."""
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smart-basket-ingest")
    parser.add_argument("chain", choices=["mercadona"])
    parser.add_argument(
        "--warehouse",
        help="warehouse code; defaults to MERCADONA_WAREHOUSES",
    )
    parser.add_argument(
        "--max-categories",
        type=_non_negative_int,
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
    warehouses = [args.warehouse] if args.warehouse else settings.mercadona_warehouse_codes
    adapter = MercadonaAdapter(delay=settings.ingest_delay_seconds)
    failed = False
    try:
        for warehouse in warehouses:
            try:
                if args.dry_run:
                    result = collect(adapter, warehouse, max_categories=args.max_categories)
                    print(
                        f"{warehouse}: categories={len(result.categories)} "
                        f"products={len(result.products)} responses={len(result.raw)} "
                        f"errors={len(result.errors)} status={result.status} "
                        f"complete={result.complete}"
                    )
                    failed = failed or result.status == "failed"
                    continue
                summary = ingest_catalog(
                    adapter,
                    warehouse,
                    data_dir=settings.data_dir,
                    max_categories=args.max_categories,
                )
                log_ingest_summary(summary)
                failed = failed or summary.status == "failed"
            except IngestSetupError:
                raise
            except Exception:
                log.exception(
                    "catalog ingestion failed for warehouse %s; continuing with the rest",
                    warehouse,
                )
                failed = True
    except IngestSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        adapter.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
