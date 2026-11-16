"""`smart-basket-match`: classify chain products into canonical products."""

import argparse
from pathlib import Path

from smart_basket.config import get_settings
from smart_basket.db import session_scope
from smart_basket.matching import (
    DecisionFileError,
    export_decisions,
    export_review,
    import_decisions,
    run,
    sync_decisions,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="smart-basket-match",
        description="Assign chain products to canonical products with the rule classifier.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    classify = commands.add_parser("run", help="classify every active chain product")
    classify.add_argument("--dry-run", action="store_true", help="decide without writing")
    classify.add_argument(
        "--report", type=Path, metavar="FILE", help="write the JSON report of the run"
    )

    export = commands.add_parser("export-review", help="write the pending reviews as JSON")
    export.add_argument("file", type=Path, help="destination JSON file")
    importer = commands.add_parser("import-decisions", help="apply the decisions of a human")
    importer.add_argument(
        "--skip-missing", action="store_true", help="skip missing products instead of failing"
    )
    importer.add_argument("file", type=Path, help="decisions JSON file")

    export_dec = commands.add_parser(
        "export-decisions", help="write review decisions as reproducible JSON"
    )
    export_dec.add_argument("file", type=Path, help="destination JSON file")

    commands.add_parser("sync", help="apply reproducible decisions and classify active products")

    args = parser.parse_args(argv)
    if args.command == "run":
        with session_scope() as session:
            result = run(session, dry_run=args.dry_run)
        if args.report is not None:
            result.write_report(args.report)
        print(result.summary)
    elif args.command == "export-review":
        with session_scope() as session:
            count = export_review(session, args.file)
        print(f"pending reviews: {count}")
    elif args.command == "import-decisions":
        with session_scope() as session:
            try:
                count = import_decisions(session, args.file, skip_missing=args.skip_missing)
            except DecisionFileError as error:
                raise SystemExit(str(error)) from error
        print(f"decisions applied: {count.applied}, skipped: {count.skipped}")
    elif args.command == "export-decisions":
        with session_scope() as session:
            count = export_decisions(session, args.file)
        print(f"decisions exported: {count}")
    elif args.command == "sync":
        with session_scope() as session:
            try:
                sync_decisions(session, get_settings())
            except ValueError as error:
                raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
