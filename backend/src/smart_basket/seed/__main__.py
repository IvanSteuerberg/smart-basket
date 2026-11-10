"""`smart-basket-seed`: load the packaged chain, zone and category seed."""

import argparse
from pathlib import Path

from smart_basket.db import session_scope
from smart_basket.seed import DEFAULT_DATA_DIR
from smart_basket.seed.loader import load_seed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="smart-basket-seed",
        description="Load chains, zones and the canonical category taxonomy.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="folder with taxonomy_es.json, chains_es.json and chain_categories/",
    )
    args = parser.parse_args(argv)
    if not args.data_dir.is_dir():
        raise SystemExit(f"seed data directory not found: {args.data_dir}")
    with session_scope() as session:
        report = load_seed(session, args.data_dir)
    print(report)


if __name__ == "__main__":
    main()
