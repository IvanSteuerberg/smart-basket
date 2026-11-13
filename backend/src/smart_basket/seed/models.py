"""Pydantic models of the seed JSON files and their joint validation (decision 0007, point 2).

The files describe the canonical category taxonomy, the chains with their zones, the brands
with their aliases and, per chain, the mapping from the chain's own category tree to taxonomy
keys. `validate_seed` checks the references that cross files.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from smart_basket.optimizer.models import BaseUnit

#: Same shape as the `category.key` and `chain.code` checks of migration 0001/0003.
KEY_PATTERN = r"^[a-z0-9_]+$"

#: Deepest level of the canonical taxonomy.
MAX_DEPTH = 3


class ZoneKind(StrEnum):
    """Zone kinds allowed by the `zone` table check."""

    CHAIN = "chain"
    POSTAL_CODE = "postal_code"
    WAREHOUSE = "warehouse"
    SALEPOINT = "salepoint"


class CategoryNode(BaseModel):
    """One node of `taxonomy_es.json`, recursive through `children`."""

    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1)
    base_unit: BaseUnit | None = None
    default_quantity: Decimal | None = Field(default=None, gt=0)
    forms: list[str] | None = None
    vague: bool = False
    children: list[CategoryNode] = Field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children


class CategoryRow(BaseModel):
    """A flattened taxonomy node, ready for the `category` table."""

    key: str
    name: str
    parent_key: str | None
    level: int
    base_unit: BaseUnit | None
    default_quantity: Decimal | None
    forms: list[str]
    is_vague: bool


class TaxonomyFile(BaseModel):
    """`taxonomy_es.json`: the canonical category tree."""

    version: int = 1
    categories: list[CategoryNode] = Field(default_factory=list)

    def walk(self) -> Iterator[tuple[CategoryNode, str | None, int]]:
        """Yield each node with its parent key and level, parents before children."""

        def visit(node: CategoryNode, parent_key: str | None, level: int):
            yield node, parent_key, level
            for child in node.children:
                yield from visit(child, node.key, level + 1)

        for node in self.categories:
            yield from visit(node, None, 1)

    def rows(self) -> list[CategoryRow]:
        """Flatten the tree, resolving `forms` defaults for leaves and inner nodes."""
        rows = []
        for node, parent_key, level in self.walk():
            forms = node.forms
            if forms is None:
                forms = [node.name.lower()] if node.is_leaf else []
            rows.append(
                CategoryRow(
                    key=node.key,
                    name=node.name,
                    parent_key=parent_key,
                    level=level,
                    base_unit=node.base_unit,
                    default_quantity=node.default_quantity,
                    forms=forms,
                    is_vague=node.vague,
                )
            )
        return rows

    @model_validator(mode="after")
    def _check_tree(self) -> TaxonomyFile:
        keys: set[str] = set()
        names: set[tuple[str | None, str]] = set()
        for node, parent_key, level in self.walk():
            if node.key in keys:
                raise ValueError(f"duplicate category key {node.key!r}")
            keys.add(node.key)
            if level > MAX_DEPTH:
                raise ValueError(f"category {node.key!r} is deeper than {MAX_DEPTH} levels")
            if node.is_leaf and node.base_unit is None:
                raise ValueError(f"leaf category {node.key!r} has no base_unit")
            if (parent_key, node.name) in names:
                raise ValueError(
                    f"duplicate category name {node.name!r} under parent {parent_key!r}"
                )
            names.add((parent_key, node.name))

        owners: dict[str, str] = {}
        for row in self.rows():
            for form in row.forms:
                normalized = form.strip().lower()
                owner = owners.setdefault(normalized, row.key)
                if owner != row.key:
                    raise ValueError(
                        f"form {normalized!r} belongs to both categories {owner!r} and {row.key!r}"
                    )
        return self


class ZoneSeed(BaseModel):
    """One zone listed for a chain in `chains_es.json`."""

    kind: ZoneKind
    code: str = Field(min_length=1)
    name: str | None = None


class ChainSeed(BaseModel):
    """One chain of `chains_es.json`."""

    code: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1)
    zones: list[ZoneSeed] = Field(default_factory=list)


class ChainsFile(BaseModel):
    """`chains_es.json`: the chains and their zones."""

    version: int = 1
    chains: list[ChainSeed] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_chains(self) -> ChainsFile:
        codes: set[str] = set()
        for chain in self.chains:
            if chain.code in codes:
                raise ValueError(f"duplicate chain code {chain.code!r}")
            codes.add(chain.code)
            zones: set[tuple[ZoneKind, str]] = set()
            for zone in chain.zones:
                if (zone.kind, zone.code) in zones:
                    raise ValueError(
                        f"duplicate zone {zone.code!r} of kind {zone.kind!r} "
                        f"in chain {chain.code!r}"
                    )
                zones.add((zone.kind, zone.code))
                if zone.kind is ZoneKind.CHAIN and zone.code != "all":
                    raise ValueError(
                        f"chain-wide zone of chain {chain.code!r} must use code 'all', "
                        f"not {zone.code!r}"
                    )
        return self


class ChainCategorySeed(BaseModel):
    """One node of a chain's own category tree."""

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    parent_code: str | None = None
    category: str | None = None


class ChainCategoriesFile(BaseModel):
    """`chain_categories/<chain_code>.json`: a chain's category tree and its mapping."""

    version: int = 1
    chain: str = Field(pattern=KEY_PATTERN)
    categories: list[ChainCategorySeed] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_categories(self) -> ChainCategoriesFile:
        codes: set[str] = set()
        for category in self.categories:
            if category.code in codes:
                raise ValueError(f"duplicate chain category code {category.code!r}")
            codes.add(category.code)
        for category in self.categories:
            if category.parent_code is not None and category.parent_code not in codes:
                raise ValueError(
                    f"chain category {category.code!r} has unknown "
                    f"parent_code {category.parent_code!r}"
                )
        parents = {category.code: category.parent_code for category in self.categories}
        for category in self.categories:
            seen = set()
            code = category.code
            while code is not None:
                if code in seen:
                    raise ValueError(f"parent_code cycle at chain category {category.code!r}")
                seen.add(code)
                code = parents[code]
        return self


class BrandSeed(BaseModel):
    """One brand of `brands_es.json`."""

    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    private_label_of: str | None = Field(default=None, pattern=KEY_PATTERN)
    implies: str | None = Field(default=None, pattern=KEY_PATTERN)

    @field_validator("aliases")
    @classmethod
    def _normalize_aliases(cls, aliases: list[str]) -> list[str]:
        normalized = []
        for alias in aliases:
            value = alias.strip().lower()
            if not value:
                raise ValueError("alias must not be empty")
            if value in normalized:
                raise ValueError(f"duplicate alias {value!r}")
            normalized.append(value)
        return normalized


class BrandsFile(BaseModel):
    """`brands_es.json`: manufacturer brands and the chains' private labels."""

    version: int = 1
    brands: list[BrandSeed] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_brands(self) -> BrandsFile:
        names: set[str] = set()
        aliases: dict[str, str] = {}
        for brand in self.brands:
            folded = brand.name.strip().lower()
            if folded in names:
                raise ValueError(f"duplicate brand name {brand.name!r}")
            names.add(folded)
            for alias in brand.aliases:
                owner = aliases.setdefault(alias, brand.name)
                if owner != brand.name:
                    raise ValueError(
                        f"alias {alias!r} belongs to both brands {owner!r} and {brand.name!r}"
                    )
        return self


def validate_seed(
    taxonomy: TaxonomyFile,
    chains: ChainsFile,
    mappings: Mapping[str, ChainCategoriesFile],
    brands: BrandsFile,
) -> None:
    """Check the references that cross the seed files.

    `mappings` is keyed by chain code (the file name without `.json`).
    """
    category_keys = {row.key for row in taxonomy.rows()}
    chain_codes = {chain.code for chain in chains.chains}
    for brand in brands.brands:
        if brand.implies is not None and brand.implies not in category_keys:
            raise ValueError(
                f"brand {brand.name!r} implies unknown taxonomy category {brand.implies!r}"
            )
        if brand.private_label_of is not None and brand.private_label_of not in chain_codes:
            raise ValueError(
                f"private label {brand.name!r} belongs to unknown chain {brand.private_label_of!r}"
            )
    for chain_code, mapping in mappings.items():
        if mapping.chain != chain_code:
            raise ValueError(f"chain_categories/{chain_code}.json declares chain {mapping.chain!r}")
        if mapping.chain not in chain_codes:
            raise ValueError(
                f"chain {mapping.chain!r} of chain_categories/{chain_code}.json "
                "does not exist in chains_es.json"
            )
        for category in mapping.categories:
            if category.category is not None and category.category not in category_keys:
                raise ValueError(
                    f"chain category {category.code!r} of chain {mapping.chain!r} maps to "
                    f"unknown taxonomy category {category.category!r}"
                )
