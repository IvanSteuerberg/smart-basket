"""Build the preprocessor lexicon from the seeded catalog and export it as JSON.

The preprocessor stays pure: this module reads the database and the packaged general
variants, and hands the result over as an `InMemoryLexicon` (decision 0014).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.preprocessor import (
    BrandTerm,
    GenericTerm,
    InMemoryLexicon,
    VariantTerm,
)
from smart_basket.seed import DEFAULT_DATA_DIR

#: General Spanish variants shipped with the seed; they are not personal vocabulary.
VARIANTS_FILE = DEFAULT_DATA_DIR / "variants_es.json"

_CATEGORIES_SQL = text(
    "select c.key, c.name, c.forms, c.base_unit, c.default_quantity, c.is_vague, "
    "  (select ancestor.key from category_closure cc "
    "   join category ancestor on ancestor.id = cc.ancestor_id "
    "   where cc.descendant_id = c.id order by cc.depth desc limit 1) as root_key "
    "from category c where cardinality(c.forms) > 0 order by c.key"
)

_BRANDS_SQL = text(
    "select id, name, is_private_label, aliases, implies_category from brand order by name, id"
)


def build_lexicon(session: Session) -> InMemoryLexicon:
    """One generic term per seeded category with forms, plus brands and general variants."""
    generic = [
        GenericTerm(
            key=row.key,
            name=row.name,
            forms=tuple(row.forms),
            base_unit=row.base_unit,
            default_quantity=row.default_quantity,
            canonical_id=None,
            category=row.root_key,
            vague=row.is_vague,
        )
        for row in session.execute(_CATEGORIES_SQL)
    ]
    brands = [
        BrandTerm(
            name=row.name,
            aliases=tuple(row.aliases) if row.aliases else (row.name.lower(),),
            is_private_label=row.is_private_label,
            brand_id=row.id,
            implies=row.implies_category,
        )
        for row in session.execute(_BRANDS_SQL)
    ]
    return InMemoryLexicon(generic, brands, _load_variants())


def _load_variants(path: Path = VARIANTS_FILE) -> list[VariantTerm]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        VariantTerm(
            key=variant["key"],
            name=variant.get("name", variant["key"]),
            forms=tuple(variant.get("forms", [variant.get("name", variant["key"])])),
        )
        for variant in data.get("variants", [])
    ]


def export_lexicon(lexicon: InMemoryLexicon, path: str | Path) -> None:
    """Write the lexicon in the JSON format `InMemoryLexicon.from_json` reads."""
    data: dict[str, list[dict[str, Any]]] = {
        "generic": [_generic_entry(g) for g in lexicon.generic_terms()],
        "brands": [_brand_entry(b) for b in lexicon.brands()],
        "variants": [_variant_entry(v) for v in lexicon.variants()],
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _generic_entry(term: GenericTerm) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": term.key,
        "name": term.name,
        "forms": list(term.forms),
        "vague": term.vague,
    }
    if term.base_unit is not None:
        entry["base_unit"] = term.base_unit
    if term.default_quantity is not None:
        entry["default_quantity"] = _json_number(term.default_quantity)
    if term.category is not None:
        entry["category"] = term.category
    if term.canonical_id is not None:
        entry["canonical_id"] = term.canonical_id
    return entry


def _brand_entry(brand: BrandTerm) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": brand.name,
        "aliases": list(brand.aliases),
        "is_private_label": brand.is_private_label,
    }
    if brand.brand_id is not None:
        entry["brand_id"] = brand.brand_id
    if brand.implies is not None:
        entry["implies"] = brand.implies
    return entry


def _variant_entry(variant: VariantTerm) -> dict[str, Any]:
    return {"key": variant.key, "name": variant.name, "forms": list(variant.forms)}


def _json_number(value: Decimal) -> int | float:
    """Integral quantities as int, the rest as float; precision fits numeric(12, 4)."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)
