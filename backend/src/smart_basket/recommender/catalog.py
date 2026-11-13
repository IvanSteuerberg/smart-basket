"""Products of the chain catalog for each requested line (decision 0016, provisional matching).

Until real product matching exists (iteration 12), the requested leaf category is the canonical
product: every chain product mapped to that category, or to a descendant, is a candidate. A leaf
without products falls back to the products of its parent group whose name resembles the text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from smart_basket.optimizer.models import BaseUnit, Line, LinePreferences, Product, Unit
from smart_basket.preprocessor.text import fold

#: Minimum `partial_ratio` between the folded item text and a fallback product name.
FALLBACK_RATIO = 80

#: Columns of `brand`; `aliases` is read only when the column exists.
_BRAND_COLUMNS_SQL = "select column_name from information_schema.columns where table_name = 'brand'"


@dataclass(frozen=True, slots=True)
class Item:
    """One requested list line, as sent by the client."""

    text: str
    category_key: str
    quantity: Decimal
    unit: Unit
    brand: str | None = None
    private_label_ok: bool = True


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    category_id: int
    parent_id: int | None
    default_quantity: Decimal | None


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One item resolved to an optimizer line and the products each candidate zone sells.

    `line` is None when the category key is unknown: the item cannot be bought and is reported
    as not available without a canonical product.
    """

    item_index: int
    text: str
    line: Line | None
    products_by_zone: Mapping[int, tuple[Product, ...]]
    product_names: Mapping[int, str]


def load_categories(session: Session, keys: set[str]) -> dict[str, CategoryInfo]:
    """Taxonomy rows for the requested keys, with the fields the line needs."""
    if not keys:
        return {}
    rows = session.execute(
        text(
            "select key, id, parent_id, default_quantity from category where key in :keys"
        ).bindparams(bindparam("keys", expanding=True)),
        {"keys": sorted(keys)},
    ).mappings()
    return {row["key"]: _category(row) for row in rows}


def _category(row: Mapping[str, Any]) -> CategoryInfo:
    return CategoryInfo(
        category_id=row["id"],
        parent_id=row["parent_id"],
        default_quantity=row["default_quantity"],
    )


def build_catalog(
    session: Session,
    items: Sequence[Item],
    categories: Mapping[str, CategoryInfo],
    zone_ids: set[int],
) -> tuple[CatalogEntry, ...]:
    """Resolve every item against the catalog of the candidate zones."""
    brands = _Brands(session)
    return tuple(
        _entry(session, index, item, categories.get(item.category_key), zone_ids, brands)
        for index, item in enumerate(items)
    )


def _entry(
    session: Session,
    index: int,
    item: Item,
    category: CategoryInfo | None,
    zone_ids: set[int],
    brands: _Brands,
) -> CatalogEntry:
    if category is None:
        return CatalogEntry(index, item.text, None, {}, {})
    brand_terms = brands.terms(item.brand) if item.brand else None
    rows = _product_rows(session, category.category_id, zone_ids)
    if not rows and category.parent_id is not None:
        rows = _fallback_rows(session, category.parent_id, item.text, zone_ids)
    products: dict[int, list[Product]] = {}
    names: dict[int, str] = {}
    for row in rows:
        product = _product(row, category.category_id, brands)
        if product is None:
            continue
        if not item.private_label_ok and product.is_private_label:
            continue
        if brand_terms is not None and not _matches_brand(row["name"], brand_terms):
            continue
        products.setdefault(row["zone_id"], []).append(product)
        names[row["product_id"]] = row["name"]
    line = Line(
        line_id=str(index),
        canonical_id=category.category_id,
        quantity=item.quantity,
        unit=item.unit,
        preferences=LinePreferences(private_label_ok=item.private_label_ok),
        default_quantity=category.default_quantity,
    )
    return CatalogEntry(
        item_index=index,
        text=item.text,
        line=line,
        products_by_zone={zone: tuple(items) for zone, items in products.items()},
        product_names=names,
    )


def _product_rows(
    session: Session, category_id: int, zone_ids: set[int]
) -> list[Mapping[str, Any]]:
    """Products mapped to `category_id` or a descendant, available with a price in each zone."""
    if not zone_ids:
        return []
    return list(
        session.execute(
            text(
                """
                select cp.id as product_id, cp.chain_id, cp.name,
                       cp.base_quantity, cp.base_unit, cp.pack_count,
                       pc.zone_id, pc.price, cc.category_id as product_category_id,
                       array(
                           select ancestor_id from category_closure
                           where descendant_id = cc.category_id
                       ) as ancestor_ids
                from chain_product cp
                join chain_category cc on cc.id = cp.chain_category_id
                join chain_product_zone cpz on cpz.chain_product_id = cp.id
                join price_current pc
                  on pc.chain_product_id = cp.id and pc.zone_id = cpz.zone_id
                where cp.is_active
                  and cpz.is_available
                  and cpz.zone_id in :zones
                  and cc.category_id in (
                      select descendant_id from category_closure
                      where ancestor_id = :category
                  )
                order by cp.id, pc.zone_id
                """
            ).bindparams(bindparam("zones", expanding=True)),
            {"zones": sorted(zone_ids), "category": category_id},
        ).mappings()
    )


def _fallback_rows(
    session: Session, group_id: int, item_text: str, zone_ids: set[int]
) -> list[Mapping[str, Any]]:
    """Products mapped directly to the parent group whose name resembles the item text."""
    rows = _product_rows(session, group_id, zone_ids)
    folded = fold(item_text)
    return [
        row
        for row in rows
        if row["product_category_id"] == group_id
        and fuzz.partial_ratio(folded, fold(row["name"])) >= FALLBACK_RATIO
    ]


def _product(row: Mapping[str, Any], canonical_id: int, brands: _Brands) -> Product | None:
    """Optimizer product, or None when the catalog has no size to compare prices by."""
    quantity, unit = row["base_quantity"], row["base_unit"]
    if quantity is None or unit is None:
        return None
    ancestors = row["ancestor_ids"] or []
    return Product(
        product_id=row["product_id"],
        canonical_id=canonical_id,
        price=row["price"],
        base_quantity=quantity,
        base_unit=BaseUnit(unit),
        pack_count=row["pack_count"],
        is_private_label=brands.is_private_label(row["chain_id"], row["name"]),
        category_ids=frozenset(ancestors),
    )


def _matches_brand(name: str, terms: set[str]) -> bool:
    folded = fold(name)
    return any(term in folded for term in terms)


class _Brands:
    """Brand names, their aliases and the private labels of each chain, read once per request."""

    def __init__(self, session: Session) -> None:
        columns = set(session.execute(text(_BRAND_COLUMNS_SQL)).scalars())
        # `brand.aliases` does not exist in this branch yet: the name alone is used then.
        self._has_aliases = "aliases" in columns
        alias = "aliases" if self._has_aliases else "null::text[] as aliases"
        self._brands = list(session.execute(text(f"select name, {alias} from brand")).mappings())
        self._private_labels: dict[int, tuple[str, ...]] = {}
        for row in session.execute(
            text(
                "select name, owner_chain_id from brand "
                "where is_private_label and owner_chain_id is not null"
            )
        ).mappings():
            folded = fold(row["name"])
            self._private_labels[row["owner_chain_id"]] = (
                *self._private_labels.get(row["owner_chain_id"], ()),
                folded,
            )

    def terms(self, brand: str) -> set[str]:
        """The folded brand name and the aliases of the matching brand."""
        target = fold(brand)
        terms = {target}
        for row in self._brands:
            if fold(row["name"]) != target:
                continue
            terms.update(fold(alias) for alias in (row["aliases"] or ()))
        return terms

    def is_private_label(self, chain_id: int, product_name: str) -> bool:
        """True when the product name contains one of its chain's private labels."""
        folded = fold(product_name)
        return any(label in folded for label in self._private_labels.get(chain_id, ()))
