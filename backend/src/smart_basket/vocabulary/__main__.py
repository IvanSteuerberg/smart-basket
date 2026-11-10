"""`smart-basket-lexicon export PATH`: build the preprocessor lexicon and write it as JSON."""

import argparse
from pathlib import Path

from smart_basket.db import session_scope
from smart_basket.vocabulary import build_lexicon, export_lexicon


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="smart-basket-lexicon",
        description="Build the preprocessor lexicon from the seeded catalog.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write the lexicon as JSON")
    export.add_argument("path", type=Path, help="destination JSON file")
    args = parser.parse_args(argv)

    with session_scope() as session:
        lexicon = build_lexicon(session)
    export_lexicon(lexicon, args.path)
    print(
        f"generic terms: {len(lexicon.generic_terms())}, "
        f"brands: {len(lexicon.brands())}, variants: {len(lexicon.variants())}"
    )


if __name__ == "__main__":
    main()
