"""Catalog quality helpers shared by ingestion and the backfill (task I17-E1).

Three pure concerns live here so the store and the backfill cannot drift apart: multipack sizes
reparsed from the product name, the extreme unit-price outlier guard (finding A1), and the
strict FR-42 `dietary_tags` extraction that only trusts explicit chain declarations.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from smart_basket.ingestion.base import BaseUnit
from smart_basket.ingestion.dia import parse_dia_size

PER_UNIT_STEP = Decimal("0.0001")

#: A unit price below these bounds cannot be real when the pack costs at least 0.50 € (A1).
MIN_KG_PRICE_PER_UNIT = Decimal("0.15")
MIN_LITRE_PRICE_PER_UNIT = Decimal("0.10")
#: A regular grocery sold above this per-unit price carries a size mis-scaled by 1000x (A1).
MAX_PRICE_PER_UNIT = Decimal("500")
CHEAP_PACK_PRICE = Decimal("0.50")

# Whole-word patterns, matched against the accent-folded, lowercase product text. Only explicit
# declarations count: the chain category never infers a tag (FR-42).
_DIETARY_TAG_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "sin_gluten": (
        re.compile(r"\bsin gluten\b"),
        re.compile(r"\bgluten free\b"),
        re.compile(r"\b0 gluten\b"),
    ),
    "sin_lactosa": (
        re.compile(r"\bsin lactosa\b"),
        re.compile(r"\blactose free\b"),
        re.compile(r"\b0 lactosa\b"),
    ),
    "vegano": (
        re.compile(r"\bvegan[oa]?\b"),
        re.compile(r"\b100 vegetal\b"),
    ),
    "vegetariano": (
        re.compile(r"\bvegetarian[oa]\b"),
        re.compile(r"\bveggie\b"),
    ),
    "ecologico": (
        re.compile(r"\becologic[oa]\b"),
        re.compile(r"\bbio\b"),
        re.compile(r"\borganic[oa]\b"),
        re.compile(r"\beco\b"),
    ),
    "sin_azucar": (
        re.compile(r"\bsin azucar(?:es)?(?: anadidos)?\b"),
        re.compile(r"\b0 azucares\b"),
        re.compile(r"\bzero azucar\b"),
    ),
}

#: Statements that veto a "free of" tag even when the positive form also appears (FR-42).
_GLUTEN_NEGATIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcon gluten\b"),
    re.compile(r"\bcontiene gluten\b"),
    re.compile(r"\btrazas de gluten\b"),
    re.compile(r"\bpuede contener gluten\b"),
    re.compile(r"\bno sin gluten\b"),
)
_LACTOSE_NEGATIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcon lactosa\b"),
    re.compile(r"\bcontiene lactosa\b"),
    re.compile(r"\btrazas de lactosa\b"),
    re.compile(r"\bpuede contener lactosa\b"),
    re.compile(r"\bno sin lactosa\b"),
)
#: "eco" is a whole word in "ahorro eco" too, where it means a saving, not organic food.
_ECO_FALSE_POSITIVE = re.compile(r"\bahorro eco\b")

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class UnitPricing:
    """The size and per-unit price the store should write after the outlier guard ran."""

    base_quantity: Decimal | None
    base_unit: BaseUnit | None
    pack_count: int
    price_per_unit: Decimal | None
    repaired: bool


def extract_dietary_tags(name: str, packaging: str | None = None) -> tuple[str, ...]:
    """Return the sorted FR-42 tags the chain explicitly declares in its name or packaging.

    Only explicit declarations count and the category never infers a tag. A negated statement
    ("con gluten", "trazas de lactosa", "no sin gluten", "puede contener gluten") vetoes the
    matching tag, and the "eco" of "ahorro eco" is not read as organic.
    """
    text = _normalize(f"{name} {packaging or ''}")
    if not text:
        return ()
    eco_text = _ECO_FALSE_POSITIVE.sub(" ", text)
    tags: set[str] = set()
    for tag, patterns in _DIETARY_TAG_PATTERNS.items():
        haystack = eco_text if tag == "ecologico" else text
        if any(pattern.search(haystack) for pattern in patterns):
            tags.add(tag)
    if "sin_gluten" in tags and any(pattern.search(text) for pattern in _GLUTEN_NEGATIONS):
        tags.discard("sin_gluten")
    if "sin_lactosa" in tags and any(pattern.search(text) for pattern in _LACTOSE_NEGATIONS):
        tags.discard("sin_lactosa")
    return tuple(sorted(tags))


def is_unit_price_outlier(
    price: Decimal,
    base_quantity: Decimal | None,
    base_unit: BaseUnit | None,
    pack_count: int,
) -> bool:
    """Whether the size and price give an impossible per-unit price (A1)."""
    if base_quantity is None or base_unit is None:
        return False
    total = base_quantity * max(pack_count, 1)
    if total <= 0:
        return True
    return _price_per_unit_outlier(price, price / total, base_unit)


def derived_price_per_unit(
    price: Decimal,
    base_quantity: Decimal | None,
    base_unit: BaseUnit | None,
    pack_count: int,
) -> Decimal | None:
    """`price / (base_quantity * pack_count)`, or None when the size cannot divide it."""
    if base_quantity is None or base_unit is None:
        return None
    total = base_quantity * max(pack_count, 1)
    if total <= 0:
        return None
    return (price / total).quantize(PER_UNIT_STEP, rounding=ROUND_HALF_UP)


def reparse_multipack_from_name(name: str) -> tuple[Decimal | None, str | None, int]:
    """Per-unit size and pack count reparsed from a product name, like the adapters do."""
    return parse_dia_size(name)


def sanitize_unit_pricing(
    name: str,
    price: Decimal,
    base_quantity: Decimal | None,
    base_unit: BaseUnit | None,
    pack_count: int,
    price_per_unit: Decimal | None = None,
) -> UnitPricing:
    """Repair or null a corrupted size and per-unit price, re-deriving them from the name.

    A row whose size yields an impossible unit price, or whose stored unit price is impossible
    for its unit, is re-derived from the multipack expression in `name` when that expression is
    itself sane; otherwise the size and the unit price are cleared together, as the
    `chain_product` check constraint requires.
    """
    pack = max(int(pack_count), 1)
    size_corrupted = is_unit_price_outlier(price, base_quantity, base_unit, pack)
    ppu_corrupted = _price_per_unit_outlier(price, price_per_unit, base_unit)
    if not size_corrupted and not ppu_corrupted:
        return UnitPricing(base_quantity, base_unit, pack, price_per_unit, False)
    if not size_corrupted and base_quantity is not None and base_unit is not None:
        recomputed = derived_price_per_unit(price, base_quantity, base_unit, pack)
        return UnitPricing(base_quantity, base_unit, pack, recomputed, True)
    quantity, unit, reparsed_pack = reparse_multipack_from_name(name)
    reparsed_pack = max(reparsed_pack, 1)
    if (
        quantity is not None
        and unit is not None
        and not is_unit_price_outlier(price, quantity, unit, reparsed_pack)
    ):
        reparsed_price = derived_price_per_unit(price, quantity, unit, reparsed_pack)
        return UnitPricing(quantity, unit, reparsed_pack, reparsed_price, True)
    return UnitPricing(None, None, pack, None, True)


def _price_per_unit_outlier(
    price: Decimal, price_per_unit: Decimal | None, base_unit: str | None
) -> bool:
    if price_per_unit is None or base_unit not in ("kg", "l"):
        return False
    minimum = MIN_KG_PRICE_PER_UNIT if base_unit == "kg" else MIN_LITRE_PRICE_PER_UNIT
    if price >= CHEAP_PACK_PRICE and price_per_unit < minimum:
        return True
    return price_per_unit > MAX_PRICE_PER_UNIT


def _normalize(text: str) -> str:
    """Fold accents and case, and turn any run of punctuation into one space."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_ALPHANUMERIC.sub(" ", plain).strip()
