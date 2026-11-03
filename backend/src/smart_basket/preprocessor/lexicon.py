"""Lexicon interface of the preprocessor and an in-memory implementation.

The real lexicon will be built from the catalog (canonical products, the seed taxonomy and
the `brand` table); tests use a synthetic fixture. No personal vocabulary lives here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GenericTerm:
    """A product type the user can ask for (a canonical product or a taxonomy leaf).

    `forms` are written forms ("pan de molde", "pan molde"); plurals ending in -s or -es match
    automatically. `vague` marks categories ("fruta", "verdura") that need a choice.
    """

    key: str
    name: str
    forms: tuple[str, ...]
    base_unit: str | None = None
    default_quantity: Decimal | None = None
    canonical_id: int | None = None
    category: str | None = None
    vague: bool = False


@dataclass(frozen=True, slots=True)
class BrandTerm:
    """A brand (from the `brand` table). `implies` names the generic term of eponymous
    products ("Cola Cao" -> cacao soluble) when the line says nothing else."""

    name: str
    aliases: tuple[str, ...]
    is_private_label: bool = False
    brand_id: int | None = None
    implies: str | None = None


@dataclass(frozen=True, slots=True)
class VariantTerm:
    """An equivalence-changing variant ("sin lactosa", "integral", "zero")."""

    key: str
    name: str
    forms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnitTerm:
    """A unit word: "kilo" is 1 kg, "docena" 12 ud, "paquete" a container counted in ud."""

    form: str
    unit: str
    factor: Decimal
    container: bool = False


class Lexicon(Protocol):
    def generic_terms(self) -> Sequence[GenericTerm]: ...

    def brands(self) -> Sequence[BrandTerm]: ...

    def variants(self) -> Sequence[VariantTerm]: ...

    def units(self) -> Sequence[UnitTerm]: ...


class InMemoryLexicon:
    def __init__(
        self,
        generic_terms: Sequence[GenericTerm],
        brands: Sequence[BrandTerm] = (),
        variants: Sequence[VariantTerm] = (),
        units: Sequence[UnitTerm] | None = None,
    ) -> None:
        from smart_basket.preprocessor.rules_es import UNITS

        self._generic = tuple(generic_terms)
        self._brands = tuple(brands)
        self._variants = tuple(variants)
        self._units = tuple(UNITS if units is None else units)

    def generic_terms(self) -> Sequence[GenericTerm]:
        return self._generic

    def brands(self) -> Sequence[BrandTerm]:
        return self._brands

    def variants(self) -> Sequence[VariantTerm]:
        return self._variants

    def units(self) -> Sequence[UnitTerm]:
        return self._units

    @classmethod
    def from_json(cls, path: str | Path) -> InMemoryLexicon:
        """Load `{"generic": [...], "brands": [...], "variants": [...]}`."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        generic = [
            GenericTerm(
                key=g["key"],
                name=g.get("name", g["key"]),
                forms=tuple(g.get("forms", [g.get("name", g["key"])])),
                base_unit=g.get("base_unit"),
                default_quantity=(
                    Decimal(str(g["default_quantity"])) if "default_quantity" in g else None
                ),
                canonical_id=g.get("canonical_id"),
                category=g.get("category"),
                vague=g.get("vague", False),
            )
            for g in data.get("generic", [])
        ]
        brands = [
            BrandTerm(
                name=b["name"],
                aliases=tuple(b.get("aliases", [b["name"]])),
                is_private_label=b.get("is_private_label", False),
                brand_id=b.get("brand_id"),
                implies=b.get("implies"),
            )
            for b in data.get("brands", [])
        ]
        variants = [
            VariantTerm(
                key=v["key"],
                name=v.get("name", v["key"]),
                forms=tuple(v.get("forms", [v.get("name", v["key"])])),
            )
            for v in data.get("variants", [])
        ]
        return cls(generic, brands, variants)
