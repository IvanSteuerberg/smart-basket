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
from smart_basket.preprocessor.text import fold, words

#: Minimum `token_set_ratio` between the folded item text and a fallback product name.
FALLBACK_RATIO = 80
#: Folded texts shorter than this are matched as whole words only, never as substrings.
SHORT_TEXT = 4

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
    """Resolve every item against the catalog of the candidate zones.

    The products of every requested category and of the parent groups the fallback may need
    are fetched once, not once per item.
    """
    brands = _Brands(session)
    resolved = [
        (index, item, categories.get(item.category_key)) for index, item in enumerate(items)
    ]
    category_ids = {category.category_id for _, _, category in resolved if category is not None}
    parent_ids = {
        category.parent_id
        for _, _, category in resolved
        if category is not None and category.parent_id is not None
    }
    rows = _product_rows(session, category_ids | parent_ids, zone_ids)
    return tuple(_entry(index, item, category, rows, brands) for index, item, category in resolved)


def _entry(
    index: int,
    item: Item,
    category: CategoryInfo | None,
    rows: Sequence[Mapping[str, Any]],
    brands: _Brands,
) -> CatalogEntry:
    if category is None:
        return CatalogEntry(index, item.text, None, {}, {})
    brand_terms = brands.terms(item.brand) if item.brand else None
    item_rows = [row for row in rows if category.category_id in (row["ancestor_ids"] or [])]
    if not item_rows and category.parent_id is not None:
        item_rows = _fallback_rows(rows, category.parent_id, item.text)
    products: dict[int, list[Product]] = {}
    names: dict[int, str] = {}
    for row in item_rows:
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
    session: Session, category_ids: set[int], zone_ids: set[int]
) -> list[Mapping[str, Any]]:
    """Products mapped to any of `category_ids` or a descendant, priced in each zone."""
    if not category_ids or not zone_ids:
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
                      where ancestor_id = any(:ids)
                  )
                order by cp.id, pc.zone_id
                """
            ).bindparams(bindparam("zones", expanding=True)),
            {"zones": sorted(zone_ids), "ids": sorted(category_ids)},
        ).mappings()
    )


def _fallback_rows(
    rows: Sequence[Mapping[str, Any]], group_id: int, item_text: str
) -> list[Mapping[str, Any]]:
    """Products mapped directly to the parent group whose name resembles the item text."""
    folded = fold(item_text)
    item_words = words(item_text)
    short = len(folded) < SHORT_TEXT
    matched = []
    for row in rows:
        if row["product_category_id"] != group_id:
            continue
        if short:
            if _contains_words(words(row["name"]), item_words):
                matched.append(row)
        elif fuzz.token_set_ratio(folded, fold(row["name"])) >= FALLBACK_RATIO:
            matched.append(row)
    return matched


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
    """True when a brand name or alias appears as whole words of the product name."""
    product_words = words(name)
    return any(_contains_words(product_words, words(term)) for term in terms)


def _contains_words(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """True when `needle` appears as a run of whole tokens in `haystack`."""
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )


class _Brands:
    """Brand names, their aliases and the private labels of each chain, read once per request."""

    def __init__(self, session: Session) -> None:
        columns = set(session.execute(text(_BRAND_COLUMNS_SQL)).scalars())
        # `brand.aliases` does not exist in this branch yet: the name alone is used then.
        alias = "aliases" if "aliases" in columns else "null::text[] as aliases"
        self._aliases: dict[str, tuple[str, ...]] = {}
        self._private_labels: dict[int, list[tuple[str, ...]]] = {}
        for row in session.execute(
            text(f"select name, {alias}, is_private_label, owner_chain_id from brand")
        ).mappings():
            folded = fold(row["name"])
            self._aliases[folded] = tuple(fold(alias) for alias in (row["aliases"] or ()))
            if row["is_private_label"] and row["owner_chain_id"] is not None:
                self._private_labels.setdefault(row["owner_chain_id"], []).append(
                    words(row["name"])
                )

    def terms(self, brand: str) -> set[str]:
        """The folded brand name and the aliases of the matching brand."""
        target = fold(brand)
        return {target, *self._aliases.get(target, ())}

    def is_private_label(self, chain_id: int, product_name: str) -> bool:
        """True when the product name has one of its chain's private labels as whole words."""
        product_words = words(product_name)
        return any(
            _contains_words(product_words, label)
            for label in self._private_labels.get(chain_id, ())
        )
