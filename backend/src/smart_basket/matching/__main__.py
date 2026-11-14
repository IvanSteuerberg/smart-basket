"""`smart-basket-match`: classify chain products into canonical products."""

import argparse
from pathlib import Path

from smart_basket.db import session_scope
from smart_basket.matching import DecisionFileError, export_review, import_decisions, run


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
    importer.add_argument("file", type=Path, help="decisions JSON file")

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
    else:
        with session_scope() as session:
            try:
                count = import_decisions(session, args.file)
            except DecisionFileError as error:
                raise SystemExit(str(error)) from error
        print(f"decisions applied: {count}")


if __name__ == "__main__":
    main()
