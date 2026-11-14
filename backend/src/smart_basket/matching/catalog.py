"""Classify chain products into canonical products and keep the review queue.

Decisions 0004, 0007 and 0015: every product goes to the leaf its section and its name allow,
or to the review queue; a human decision closes the review. The rules are pure (`matching.rules`
and `matching.names`); this module loads the taxonomy and the catalog, writes the canonicals and
the matches, and reads and writes the review files.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.matching.names import canonical_name, name_match, variant_key
from smart_basket.matching.rules import Candidate, Section, decide
from smart_basket.preprocessor import Preprocessor
from smart_basket.vocabulary import build_lexicon

#: Methods a run never overwrites: a human decision and the stronger EAN or embedding matches.
PROTECTED_METHODS = ("review", "ean", "embedding")


@dataclass(frozen=True, slots=True)
class MatchSummary:
    """What one classifier run did, for the caller to log and for tests to assert."""

    products: int
    assigned: int
    review: int
    unchanged: int

    @property
    def assigned_share(self) -> float:
        return 100.0 * self.assigned / self.products if self.products else 0.0

    def __str__(self) -> str:
        return (
            f"products {self.products}, assigned {self.assigned} "
            f"({self.assigned_share:.1f} %), review {self.review}, unchanged {self.unchanged}"
        )


@dataclass(frozen=True, slots=True)
class LeafReport:
    """The products of one leaf, for a human to spot leaves that mix product types."""

    category_key: str
    name: str
    assigned: int
    products: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "category_key": self.category_key,
            "name": self.name,
            "assigned": self.assigned,
            "products": list(self.products),
        }


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """A product waiting for a human decision, as the review files carry it."""

    product_id: int
    sku: str
    name: str
    section: str | None
    candidates: tuple[Candidate, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "sku": self.sku,
            "name": self.name,
            "section": self.section,
            "candidates": [
                {"category_key": candidate.category_key, "why": candidate.why}
                for candidate in self.candidates
            ],
        }


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The outcome of a run: counters plus what the report and the review queue show."""

    summary: MatchSummary
    leaves: tuple[LeafReport, ...]
    review: tuple[ReviewItem, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "leaves": [leaf.to_json() for leaf in self.leaves],
            "review": [item.to_json() for item in self.review],
        }

    def write_report(self, path: Path) -> None:
        write_json(path, self.to_json())


class DecisionFileError(ValueError):
    """A decisions file the importer cannot apply; the message names the line."""


@dataclass(frozen=True, slots=True)
class Node:
    """A node of the seeded category tree."""

    id: int
    key: str
    name: str
    parent_id: int | None
    base_unit: str | None
    default_quantity: Decimal | None
    is_leaf: bool


@dataclass(frozen=True, slots=True)
class Product:
    """An active chain product and where its chain section places it in the taxonomy."""

    id: int
    sku: str
    name: str
    canonical_id: int | None
    match_method: str | None
    section_id: int | None
    category_id: int | None


class Taxonomy:
    """The category tree in memory, with the subtree of every node from the closure table."""

    def __init__(self, nodes: Sequence[Node], subtree: dict[int, frozenset[int]]) -> None:
        self.nodes = {node.id: node for node in nodes}
        self.by_key = {node.key: node for node in nodes}
        self.leaves = {node.key: node for node in nodes if node.is_leaf}
        self.leaf_keys = frozenset(self.leaves)
        self._subtree = subtree
        self._sections: dict[int | None, Section] = {}

    def section(self, node_id: int | None) -> Section:
        """The allowed subtree of the section mapped to `node_id`, cached per node."""
        if node_id not in self._sections:
            self._sections[node_id] = self._section(node_id)
        return self._sections[node_id]

    def _section(self, node_id: int | None) -> Section:
        node = self.nodes.get(node_id) if node_id is not None else None
        if node is None:
            return Section(None, False, frozenset(), frozenset())
        allowed = set(self._subtree.get(node.id, frozenset()))
        if node.is_leaf and node.parent_id is not None:
            allowed |= self._subtree.get(node.parent_id, frozenset())
        ancestors: set[str] = set()
        parent = node.parent_id
        while parent is not None and parent in self.nodes:
            ancestors.add(self.nodes[parent].key)
            parent = self.nodes[parent].parent_id
        return Section(
            key=node.key,
            is_leaf=node.is_leaf,
            ancestors=frozenset(ancestors),
            allowed_leaves=frozenset(
                self.nodes[child].key for child in allowed if self.nodes[child].is_leaf
            ),
        )


def load_taxonomy(session: Session) -> Taxonomy:
    """The categories and their closure, with leaves told apart by having no children."""
    rows = list(
        session.execute(
            text(
                "select id, key, name, parent_id, base_unit, default_quantity "
                "from category order by id"
            )
        ).mappings()
    )
    parents = {row["parent_id"] for row in rows if row["parent_id"] is not None}
    nodes = [
        Node(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            parent_id=row["parent_id"],
            base_unit=row["base_unit"],
            default_quantity=row["default_quantity"],
            is_leaf=row["id"] not in parents,
        )
        for row in rows
    ]
    for node in nodes:
        if node.is_leaf and node.base_unit is None:
            # `canonical_product.base_unit` is not null: a leaf without one cannot hold products.
            raise ValueError(f"leaf category {node.key!r} has no base_unit")

    subtree: dict[int, set[int]] = {node.id: {node.id} for node in nodes}
    for row in session.execute(text("select ancestor_id, descendant_id from category_closure")):
        subtree.setdefault(row.ancestor_id, set()).add(row.descendant_id)
    return Taxonomy(nodes, {key: frozenset(ids) for key, ids in subtree.items()})


def load_products(session: Session) -> list[Product]:
    """Every active chain product, with the taxonomy node of its chain section."""
    return [
        Product(
            id=row["id"],
            sku=row["chain_sku"],
            name=row["name"],
            canonical_id=row["canonical_id"],
            match_method=row["match_method"],
            section_id=row["chain_category_id"],
            category_id=row["category_id"],
        )
        for row in session.execute(
            text(
                "select cp.id, cp.chain_sku, cp.name, cp.canonical_id, cp.match_method, "
                "  cp.chain_category_id, cc.category_id "
                "from chain_product cp "
                "left join chain_category cc on cc.id = cp.chain_category_id "
                "where cp.is_active order by cp.id"
            )
        ).mappings()
    ]


def run(session: Session, *, dry_run: bool = False) -> MatchResult:
    """Classify every active product; with `dry_run`, decide but write nothing."""
    taxonomy = load_taxonomy(session)
    preprocessor = Preprocessor(build_lexicon(session))
    variant_names = {term.key: term.name for _form, term in preprocessor.variant_forms}
    canonical_ids = _load_canonicals(session)
    pending = set(
        session.execute(
            text("select chain_product_id from match_review where status = 'pending'")
        ).scalars()
    )
    sections = section_paths(session)
    reviews_before = pending_reviews(session, sections) if dry_run else ()

    products = load_products(session)
    by_leaf: dict[str, list[tuple[int, str]]] = defaultdict(list)
    planned: list[ReviewItem] = []
    assigned = review = unchanged = 0

    for product in products:
        if product.id in pending or product.match_method in PROTECTED_METHODS:
            unchanged += 1
            continue

        match = name_match(preprocessor, product.name)
        decision = decide(match, taxonomy.section(product.category_id), taxonomy.leaf_keys)
        if decision.in_review:
            review += 1
            planned.append(
                ReviewItem(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    section=sections.get(product.section_id),
                    candidates=decision.candidates,
                )
            )
            if not dry_run:
                _queue_review(session, product.id, decision.candidates)
                _clear_rule_assignment(session, product.id)
            continue

        assert decision.category_key is not None  # not in review
        leaf = taxonomy.by_key[decision.category_key]
        keys = match.variant_keys
        name = canonical_name(leaf.name, keys, variant_names)
        key = (leaf.id, name, variant_key(keys))
        canonical_id = canonical_ids.get(key)
        if canonical_id is None:
            changed = True
            if not dry_run:
                canonical_id = _insert_canonical(session, leaf, name, key[2])
                canonical_ids[key] = canonical_id
        else:
            changed = canonical_id != product.canonical_id
        if changed:
            assigned += 1
            if not dry_run:
                _assign(session, product.id, canonical_id, decision.confidence)
        else:
            unchanged += 1
        by_leaf[leaf.key].append((product.id, product.name))

    leaves = tuple(
        LeafReport(
            category_key=key,
            name=taxonomy.by_key[key].name,
            assigned=len(by_leaf[key]),
            products=_unique_names(by_leaf[key]),
        )
        for key in sorted(by_leaf)
    )
    review_items = (
        pending_reviews(session, sections) if not dry_run else _merge(reviews_before, planned)
    )
    summary = MatchSummary(
        products=len(products), assigned=assigned, review=review, unchanged=unchanged
    )
    return MatchResult(summary=summary, leaves=leaves, review=review_items)


def pending_reviews(
    session: Session, sections: dict[int, str] | None = None
) -> tuple[ReviewItem, ...]:
    """The reviews still waiting for a human decision."""
    paths = section_paths(session) if sections is None else sections
    return tuple(
        ReviewItem(
            product_id=row["chain_product_id"],
            sku=row["chain_sku"],
            name=row["name"],
            section=paths.get(row["chain_category_id"]),
            candidates=tuple(
                Candidate(candidate["category_key"], candidate.get("why", ""))
                for candidate in row["candidates"]
            ),
        )
        for row in session.execute(
            text(
                "select mr.chain_product_id, mr.candidates, cp.chain_sku, cp.name, "
                "  cp.chain_category_id "
                "from match_review mr join chain_product cp on cp.id = mr.chain_product_id "
                "where mr.status = 'pending' order by mr.chain_product_id"
            )
        ).mappings()
    )


def export_review(session: Session, path: Path) -> int:
    """Write the pending reviews as JSON where the user says, and return how many there are."""
    items = pending_reviews(session)
    write_json(path, [item.to_json() for item in items])
    return len(items)


def import_decisions(session: Session, path: Path) -> int:
    """Apply a human's decisions: assign with method `review` and accept the review.

    The file is a JSON array of `{"product_id", "category_key", "variant_key"}`. An unknown
    key is an error that names the line; the caller rolls the whole file back.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise DecisionFileError("the decisions file must be a JSON array")
    taxonomy = load_taxonomy(session)
    variant_names = _variant_names(session)
    product_ids = set(session.execute(text("select id from chain_product")).scalars())
    canonical_ids = _load_canonicals(session)
    applied = 0
    for line, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise DecisionFileError(f"line {line}: expected an object")
        product_id = entry.get("product_id")
        if not isinstance(product_id, int) or product_id not in product_ids:
            raise DecisionFileError(f"line {line}: product {product_id!r} does not exist")
        leaf = taxonomy.leaves.get(entry.get("category_key"))
        if leaf is None:
            raise DecisionFileError(
                f"line {line}: unknown category key {entry.get('category_key')!r}"
            )
        keys = _variant_keys(entry.get("variant_key", ""), line, variant_names)
        name = canonical_name(leaf.name, keys, variant_names)
        key = (leaf.id, name, variant_key(keys))
        canonical_id = canonical_ids.get(key)
        if canonical_id is None:
            canonical_id = _insert_canonical(session, leaf, name, key[2])
            canonical_ids[key] = canonical_id
        _assign(session, product_id, canonical_id, 1.0, method="review")
        session.execute(
            text(
                "update match_review set status = 'accepted', resolved_at = now() "
                "where chain_product_id = :product and status = 'pending'"
            ),
            {"product": product_id},
        )
        applied += 1
    return applied


def write_json(path: Path, data: Any) -> None:
    """Write collected-catalog files where the user asked, never inside the repository."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def section_paths(session: Session) -> dict[int, str]:
    """The chain section path of every `chain_category` ("Fruta > Plátano y uva")."""
    rows = list(
        session.execute(
            text("select id, chain_id, code, name, parent_code from chain_category")
        ).mappings()
    )
    by_code = {(row["chain_id"], row["code"]): row for row in rows}
    paths: dict[int, str] = {}
    for row in rows:
        names = [row["name"]]
        seen = {row["code"]}
        current = row
        while current["parent_code"] is not None:
            parent = by_code.get((current["chain_id"], current["parent_code"]))
            if parent is None or parent["code"] in seen:
                break
            names.append(parent["name"])
            seen.add(parent["code"])
            current = parent
        paths[row["id"]] = " > ".join(reversed(names))
    return paths


def _load_canonicals(session: Session) -> dict[tuple[int, str, str], int]:
    """The canonicals by natural key, so a run knows what already exists."""
    return {
        (row.category_id, row.name, row.variant_key): row.id
        for row in session.execute(
            text("select id, category_id, name, variant_key from canonical_product")
        )
    }


def _insert_canonical(session: Session, leaf: Node, name: str, variants: str) -> int:
    return session.execute(
        text(
            "insert into canonical_product (category_id, name, variant_key, base_unit, "
            "  default_quantity) values (:category, :name, :variant, :unit, :quantity) "
            "returning id"
        ),
        {
            "category": leaf.id,
            "name": name,
            "variant": variants,
            "unit": leaf.base_unit,
            "quantity": leaf.default_quantity,
        },
    ).scalar_one()


def _assign(
    session: Session,
    product_id: int,
    canonical_id: int | None,
    confidence: float | None,
    method: str = "rule",
) -> None:
    """Point the product at the canonical and record the match, only when it changed."""
    updated = session.execute(
        text(
            "update chain_product set canonical_id = :canonical, match_method = :method, "
            "  match_confidence = :confidence "
            "where id = :product "
            "  and (canonical_id is distinct from :canonical "
            "       or match_method is distinct from :method) returning id"
        ),
        {
            "product": product_id,
            "canonical": canonical_id,
            "method": method,
            "confidence": confidence,
        },
    ).scalar_one_or_none()
    if updated is None:
        return
    session.execute(
        text(
            "insert into product_match (chain_product_id, canonical_id, method, score) "
            "values (:product, :canonical, :method, :score)"
        ),
        {
            "product": product_id,
            "canonical": canonical_id,
            "method": method,
            "score": confidence,
        },
    )


def _queue_review(session: Session, product_id: int, candidates: Sequence[Candidate]) -> None:
    """Open a pending review, at most one per product."""
    session.execute(
        text(
            "insert into match_review (chain_product_id, candidates) "
            "values (:product, cast(:candidates as jsonb)) "
            "on conflict (chain_product_id) where status = 'pending' do nothing"
        ),
        {
            "product": product_id,
            "candidates": json.dumps(
                [
                    {"category_key": candidate.category_key, "why": candidate.why}
                    for candidate in candidates
                ],
                ensure_ascii=False,
            ),
        },
    )


def _clear_rule_assignment(session: Session, product_id: int) -> None:
    """A doubt takes the product out of the canonical a rule gave it; humans and EAN stay."""
    session.execute(
        text(
            "update chain_product set canonical_id = null, match_method = null, "
            "  match_confidence = null where id = :product and match_method = 'rule'"
        ),
        {"product": product_id},
    )


def _variant_names(session: Session) -> dict[str, str]:
    return {term.key: term.name for term in build_lexicon(session).variants()}


def _variant_keys(raw: Any, line: int, names: dict[str, str]) -> tuple[str, ...]:
    if not isinstance(raw, str):
        raise DecisionFileError(f"line {line}: variant_key must be a string")
    keys = [key for key in raw.split("|") if key]
    for key in keys:
        flavour = key.startswith("sabor:") and len(key) > len("sabor:")
        if key not in names and not flavour:
            raise DecisionFileError(f"line {line}: unknown variant key {key!r}")
    return tuple(sorted(set(keys)))


def _unique_names(products: Sequence[tuple[int, str]]) -> tuple[str, ...]:
    names: dict[str, None] = {}
    for _product_id, name in products:
        names.setdefault(name, None)
    return tuple(names)


def _merge(before: Sequence[ReviewItem], planned: Sequence[ReviewItem]) -> tuple[ReviewItem, ...]:
    """The reviews already pending plus the ones this run would open, without duplicates."""
    items = {item.product_id: item for item in before}
    for item in planned:
        items.setdefault(item.product_id, item)
    return tuple(items[key] for key in sorted(items))
