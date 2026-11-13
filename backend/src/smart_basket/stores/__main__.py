"""`smart-basket-stores`: import the supermarkets of León from OpenStreetMap."""

import argparse
import logging
import sys

from smart_basket.config import get_settings
from smart_basket.stores.osm import BoundingBox, OverpassClient, OverpassError, fetch_stores
from smart_basket.stores.store import (
    StoreSetupError,
    count_by_chain,
    import_stores,
    log_store_summary,
)

log = logging.getLogger("smart_basket.stores")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smart-basket-stores")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="fetch the stores and load them")
    importer.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and parse without touching the database",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        bbox = BoundingBox.parse(settings.stores_bbox)
        with OverpassClient(url=settings.overpass_url) as client:
            observations = fetch_stores(client, bbox)
        if args.dry_run:
            for chain_code, count in count_by_chain(observations).items():
                print(f"{chain_code}: {count}")
            return 0
        summary = import_stores(observations)
        log_store_summary(summary)
        for chain_code, count in summary.per_chain.items():
            print(f"{chain_code}: {count}")
    except StoreSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OverpassError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
