"""`smart-basket-catalog-agent`: embed, calibrate, run, undo and audit the catalog agent.

Every subcommand opens the configured database for the duration of one operation:

* `embed` fills the missing `vector(768)` columns with the configured embedding provider;
* `calibrate` reports precision and coverage per similarity threshold;
* `run` lets the agent assign, propose leaves and queue reviews over unmatched products;
* `undo-leaf` reverses one applied `catalog_leaf_proposal`;
* `audit-sample` produces a blind, deterministic sample of matched products.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from smart_basket.agent.catalog_executors import (
    calibrate_thresholds,
    export_audit_sample,
    run_catalog_agent,
    undo_leaf_proposal,
)
from smart_basket.config import get_settings
from smart_basket.db import session_scope
from smart_basket.llm.embeddings import embedding_provider_from_settings
from smart_basket.matching.embeddings import embed_missing_canonicals, embed_missing_products


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser, also used by the tests to check every subcommand parses."""
    parser = argparse.ArgumentParser(
        prog="smart-basket-catalog-agent",
        description="Catalog Agent: pgvector embeddings, calibration, runs and audits (ADR 0022).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    embed = commands.add_parser("embed", help="fill the missing canonical and product embeddings")
    embed.add_argument("--chain", default=None, help="only embed products of this chain code")
    embed.add_argument("--batch-size", type=int, default=100, help="rows per provider call")
    embed.add_argument(
        "--skip-canonicals", action="store_true", help="do not embed canonical products"
    )
    embed.add_argument("--skip-products", action="store_true", help="do not embed chain products")

    calibrate = commands.add_parser(
        "calibrate", help="precision and coverage per similarity threshold"
    )
    calibrate.add_argument("--chain", default=None, help="only use products of this chain")
    calibrate.add_argument("--sample-size", type=int, default=200, help="matched products to use")
    calibrate.add_argument("--output", type=Path, default=None, help="write the JSON summary")

    run = commands.add_parser("run", help="run the catalog agent over unmatched products")
    run.add_argument("--chain", default=None, help="only process products of this chain")
    run.add_argument(
        "--tau-high", type=float, default=0.88, help="similarity that assigns without review"
    )
    run.add_argument("--top-k", type=int, default=5, help="canonicals offered per product")
    run.add_argument("--limit", type=int, default=None, help="maximum products to process")
    run.add_argument("--output", type=Path, default=None, help="write the JSON summary")

    undo = commands.add_parser("undo-leaf", help="reverse an applied leaf proposal")
    undo.add_argument("proposal_id", type=int, help="catalog_leaf_proposal id")

    audit = commands.add_parser("audit-sample", help="blind deterministic audit sample")
    audit.add_argument("--chain", required=True, help="chain code to sample")
    audit.add_argument("--sample-size", type=int, default=250, help="products to sample")
    audit.add_argument("--seed", type=int, default=42, help="sampling seed")
    audit.add_argument("--output", type=Path, default=None, help="write the JSON sample")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "embed":
        provider = embedding_provider_from_settings(get_settings())
        with session_scope() as session:
            canonicals = (
                0
                if args.skip_canonicals
                else embed_missing_canonicals(session, provider, batch_size=args.batch_size)
            )
            products = (
                0
                if args.skip_products
                else embed_missing_products(
                    session, provider, chain_code=args.chain, batch_size=args.batch_size
                )
            )
        print(f"canonicals embedded: {canonicals}; products embedded: {products}")
    elif args.command == "calibrate":
        with session_scope() as session:
            summary = calibrate_thresholds(
                session, chain_code=args.chain, sample_size=args.sample_size
            )
        if args.output is not None:
            _write_json(args.output, summary)
        _print_calibration(summary)
    elif args.command == "run":
        with session_scope() as session:
            summary = run_catalog_agent(
                session,
                chain_code=args.chain,
                tau_high=args.tau_high,
                top_k=args.top_k,
                limit=args.limit,
            )
        printable = {**summary, "run_id": str(summary["run_id"])}
        if args.output is not None:
            _write_json(args.output, printable)
        print(
            f"run {printable['run_id']}: assigned {summary['assigned']}, "
            f"leaves {summary['proposed_leaves']}, review {summary['sent_to_review']}, "
            f"steps {summary['steps']} ({summary['status']})"
        )
    elif args.command == "undo-leaf":
        with session_scope() as session:
            try:
                summary = undo_leaf_proposal(session, args.proposal_id)
            except ValueError as error:
                raise SystemExit(str(error)) from error
        print(
            f"proposal {summary['proposal_id']}: {summary['status']}, "
            f"products cleared {summary['products_cleared']}, "
            f"reviews queued {summary['reviews_queued']}"
        )
    elif args.command == "audit-sample":
        with session_scope() as session:
            sample = export_audit_sample(
                session, chain_code=args.chain, sample_size=args.sample_size, seed=args.seed
            )
        if args.output is not None:
            _write_json(args.output, sample)
        print(f"{args.chain}: {len(sample)} products sampled for audit")
    return 0


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_calibration(summary: dict[str, Any]) -> None:
    print(f"chain: {summary['chain_code'] or 'all'}; sample: {summary['sample_size']}")
    print(f"{'threshold':>9} {'precision':>10} {'coverage':>9} {'auto':>6}")
    for row in summary["thresholds"]:
        print(
            f"{row['threshold']:>9.2f} {row['precision']:>10.1%} "
            f"{row['coverage']:>9.1%} {row['auto_assigned']:>6}"
        )


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
