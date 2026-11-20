"""`smart-basket-ingest`: crawl one chain manually, optionally without touching the database."""

import argparse
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass

from smart_basket.config import Settings, get_settings
from smart_basket.ingestion.alimerka import AlimerkaAdapter
from smart_basket.ingestion.backfill import backfill_images
from smart_basket.ingestion.base import ChainAdapter, collect
from smart_basket.ingestion.dia import DiaAdapter
from smart_basket.ingestion.gadis import GadisAdapter
from smart_basket.ingestion.lupa import LupaAdapter
from smart_basket.ingestion.mercadona import MercadonaAdapter
from smart_basket.ingestion.store import IngestSetupError, ingest_catalog, log_ingest_summary

log = logging.getLogger("smart_basket.ingestion")


@dataclass(frozen=True, slots=True)
class ChainEntry:
    """How to build one chain's adapter and which zones it crawls when none is given."""

    adapter: Callable[..., ChainAdapter]
    zones: Callable[[Settings], list[str]]


#: Every chain the CLI and the worker can ingest; supporting a chain is adding one entry here.
ADAPTERS: dict[str, ChainEntry] = {
    "mercadona": ChainEntry(
        adapter=MercadonaAdapter,
        zones=lambda settings: settings.mercadona_warehouse_codes,
    ),
    "dia": ChainEntry(
        adapter=DiaAdapter,
        zones=lambda settings: settings.dia_zone_codes,
    ),
    "gadis": ChainEntry(
        adapter=GadisAdapter,
        zones=lambda settings: settings.gadis_zone_codes,
    ),
    "alimerka": ChainEntry(
        adapter=AlimerkaAdapter,
        zones=lambda settings: settings.alimerka_zone_codes,
    ),
    "lupa": ChainEntry(
        adapter=LupaAdapter,
        zones=lambda settings: settings.lupa_zone_codes,
    ),
}


def _non_negative_int(value: str) -> int:
    """Argparse type for counts that cannot be negative."""
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smart-basket-ingest")
    parser.add_argument("chain", choices=sorted(ADAPTERS))
    parser.add_argument(
        "--zone",
        "--warehouse",
        dest="zone",
        help="zone code (warehouse, postal code, sale point); defaults to the chain's zones",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--max-categories",
        type=_non_negative_int,
        default=None,
        help="crawl only the first N level 2 categories (the run is then incomplete)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="crawl and parse without touching the database",
    )
    mode.add_argument(
        "--backfill-images",
        action="store_true",
        help="fill product photos from the saved raw responses, without crawling",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.backfill_images:
        summary = backfill_images(args.chain, data_dir=settings.data_dir)
        print(summary.message())
        return 0
    entry = ADAPTERS[args.chain]
    zones = [args.zone] if args.zone else entry.zones(settings)
    adapter = entry.adapter(delay=settings.ingest_delay_seconds)
    failed = False
    try:
        for zone in zones:
            try:
                if args.dry_run:
                    result = collect(adapter, zone, max_categories=args.max_categories)
                    print(
                        f"{zone}: categories={len(result.categories)} "
                        f"products={len(result.products)} responses={len(result.raw)} "
                        f"errors={len(result.errors)} status={result.status} "
                        f"complete={result.complete}"
                    )
                    failed = failed or result.status == "failed"
                    continue
                summary = ingest_catalog(
                    adapter,
                    zone,
                    data_dir=settings.data_dir,
                    max_categories=args.max_categories,
                )
                log_ingest_summary(summary)
                failed = failed or summary.status == "failed"
            except IngestSetupError:
                raise
            except Exception:
                log.exception(
                    "catalog ingestion failed for zone %s of chain %s; continuing with the rest",
                    zone,
                    args.chain,
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
