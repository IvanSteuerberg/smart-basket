"""Products of the chain catalog for each requested line, resolved through canonical products.

Every chain product has a canonical product (decision 0004): a leaf of the taxonomy plus the
variants that change equivalence, without brand or size. A generic line takes the products of
the canonicals under the requested category whose variant set matches the line; a concrete line
takes one product (exact) or every product of its canonical (equivalent). Each line gets a
synthetic canonical id inside the optimizer, so two lines of the same canonical do not share
products and options, while the response reports the real canonical of the chosen product.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from smart_basket.brands import Brands, matches_brand
from smart_basket.optimizer.models import BaseUnit, Line, LinePreferences, Product, Unit
from smart_basket.preprocessor import rules_es as R
from smart_basket.preprocessor.text import same_word, words
from smart_basket.seed import DEFAULT_DATA_DIR

#: How strictly a concrete line accepts the products of its canonical product.
Accept = Literal["exact", "equivalent"]

#: Measured dimension of each base unit. A product measured by mass cannot satisfy a line
#: measured by volume or the other way round; counted lines accept weighed products (bread by kg).
_DIMENSIONS = {"kg": "mass", "g": "mass", "l": "volume", "ml": "volume"}
#: General Spanish variants shipped with the seed; their forms tell "integral" from "tiburón".
VARIANTS_FILE = DEFAULT_DATA_DIR / "variants_es.json"


class UnknownProduct(Exception):
    """A line names a product id that is not an active chain product."""


@dataclass(frozen=True, slots=True)
class Item:
    """One requested list line, as sent by the client.

    Exactly one of `category_key` (generic line) and `product_id` (concrete line) is set.
    """

    text: str
    category_key: str | None = None
    product_id: int | None = None
    accept: Accept = "equivalent"
    variants: tuple[str, ...] | None = None
    quantity: Decimal = Decimal(1)
    unit: Unit = Unit.UD
    brand: str | None = None
    private_label_ok: bool = True


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    category_id: int
    parent_id: int | None
    name: str
    default_quantity: Decimal | None
    base_unit: str | None
    is_vague: bool
    #: Leaf of products that are never interchangeable (shades): only a concrete product is bought.
    exact_only: bool = False


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
    product_canonicals: Mapping[int, int | None]
    product_brands: Mapping[int, str | None]
    product_images: Mapping[int, str | None]
    #: Whether the line asked for a concrete product with `accept="exact"`.
    exact: bool


@dataclass(frozen=True, slots=True)
class VariantTerm:
    """One general variant, with the word forms that name it in a text or product name.

    `plain` marks a canonical variant that a line without variants still accepts ("atún"
    takes tinned tuna in olive oil); the rest change the product enough to be asked for.
    """

    key: str
    forms: tuple[tuple[str, ...], ...]
    canonical: bool
    plain: bool = False


def load_categories(session: Session, keys: set[str]) -> dict[str, CategoryInfo]:
    """Taxonomy rows for the requested keys, with the fields the line needs."""
    if not keys:
        return {}
    rows = session.execute(
        text(
            "select key, id, parent_id, name, default_quantity, base_unit, is_vague, "
            "exact_only "
            "from category where key in :keys"
        ).bindparams(bindparam("keys", expanding=True)),
        {"keys": sorted(keys)},
    ).mappings()
    return {row["key"]: _category(row) for row in rows}


def _category(row: Mapping[str, Any]) -> CategoryInfo:
    return CategoryInfo(
        category_id=row["id"],
        parent_id=row["parent_id"],
        name=row["name"],
        default_quantity=row["default_quantity"],
        base_unit=row["base_unit"],
        is_vague=row["is_vague"],
        exact_only=row["exact_only"],
    )


def build_catalog(
    session: Session,
    items: Sequence[Item],
    categories: Mapping[str, CategoryInfo],
    zone_ids: set[int],
) -> tuple[CatalogEntry, ...]:
    """Resolve every item against the priced products of the candidate zones."""
    brands = Brands(session)
    rows = _product_rows(session, zone_ids)
    return tuple(
        _entry(
            index,
            item,
            categories.get(item.category_key) if item.category_key else None,
            rows,
            brands,
            session,
        )
        for index, item in enumerate(items)
    )


def _entry(
    index: int,
    item: Item,
    category: CategoryInfo | None,
    rows: Sequence[Mapping[str, Any]],
    brands: Brands,
    session: Session,
) -> CatalogEntry:
    if item.product_id is not None:
        return _concrete_entry(index, item, rows, brands, session)
    if category is None:
        return CatalogEntry(index, item.text, None, {}, {}, {}, {}, {}, item.accept == "exact")
    return _generic_entry(index, item, category, rows, brands)


def _generic_entry(
    index: int,
    item: Item,
    category: CategoryInfo,
    rows: Sequence[Mapping[str, Any]],
    brands: Brands,
) -> CatalogEntry:
    # Products without a canonical product are never candidates of a generic line.
    item_rows = [
        row
        for row in rows
        if row["canonical_id"] is not None and category.category_id in (row["ancestor_ids"] or [])
    ]
    requested = _requested_variants(item)
    terms = _term_by_key()
    canonical_keys = frozenset(key for key in requested if terms[key].canonical)
    groups: dict[int, frozenset[str]] = {}
    for row in item_rows:
        groups.setdefault(row["canonical_id"], _variant_keys(row["variant_key"]))
    if canonical_keys:
        chosen_ids = {
            canonical_id for canonical_id, keys in groups.items() if keys == canonical_keys
        }
        if not chosen_ids:
            chosen_ids = {
                canonical_id for canonical_id, keys in groups.items() if canonical_keys <= keys
            }
    else:
        # Without a requested variant, the plain canonicals are the ordinary products: one
        # with no variant at all, or only variants that do not really change it.
        chosen_ids = {
            canonical_id
            for canonical_id, keys in groups.items()
            if all(_is_plain(key) for key in keys)
        }
        if not chosen_ids:
            chosen_ids = set(groups)
    item_rows = [row for row in item_rows if row["canonical_id"] in chosen_ids]
    # Variants that do not change the canonical still filter products by name.
    name_variants = [key for key in requested if not terms[key].canonical]
    item_rows = _with_variant_names(item_rows, name_variants)
    # Words beyond the category (and the variants) narrow the canonicals the same way.
    item_rows = _with_line_words(item_rows, _content_words(item, category, brands))
    canonical_id = -(index + 1)
    chosen = _candidates(item_rows, item, brands, category.base_unit, canonical_id)
    products_by_zone, names, canonicals, brand_names, images = _collect(chosen, brands)
    line = Line(
        line_id=str(index),
        canonical_id=canonical_id,
        quantity=item.quantity,
        unit=item.unit,
        preferences=LinePreferences(private_label_ok=item.private_label_ok),
        default_quantity=_default_quantity(item, category, chosen),
    )
    return CatalogEntry(
        index, item.text, line, products_by_zone, names, canonicals, brand_names, images, False
    )


def _concrete_entry(
    index: int,
    item: Item,
    rows: Sequence[Mapping[str, Any]],
    brands: Brands,
    session: Session,
) -> CatalogEntry:
    header = _product_header(session, item.product_id)
    if header is None:
        raise UnknownProduct
    # Products of an exact-only leaf are never swapped for another one of the canonical product.
    equivalent = item.accept == "equivalent" and not header["exact_only"]
    canonical = header["canonical_id"] if equivalent else None
    if canonical is not None:
        item_rows = [row for row in rows if row["canonical_id"] == canonical]
    else:
        item_rows = [row for row in rows if row["product_id"] == item.product_id]
    canonical_id = -(index + 1)
    chosen = _candidates(item_rows, item, brands, header["base_unit"], canonical_id)
    quantity, unit = _concrete_quantity(item, header)
    preferences = LinePreferences(private_label_ok=item.private_label_ok)
    if item.accept == "exact" or canonical is None:
        preferences = LinePreferences(
            pack_quantity=_pack_size(header),
            private_label_ok=item.private_label_ok,
        )
    products_by_zone, names, canonicals, brand_names, images = _collect(chosen, brands)
    line = Line(
        line_id=str(index),
        canonical_id=canonical_id,
        quantity=quantity,
        unit=unit,
        preferences=preferences,
        default_quantity=None,
    )
    return CatalogEntry(
        index,
        item.text,
        line,
        products_by_zone,
        names,
        canonicals,
        brand_names,
        images,
        item.accept == "exact",
    )


def _product_header(session: Session, product_id: int) -> Mapping[str, Any] | None:
    """Size and canonical of an active product, or None when the id does not exist."""
    return (
        session.execute(
            text(
                "select p.id, p.canonical_id, p.base_quantity, p.base_unit, p.pack_count, "
                "coalesce(c.exact_only, false) as exact_only "
                "from chain_product p "
                "left join canonical_product cp on cp.id = p.canonical_id "
                "left join category c on c.id = cp.category_id "
                "where p.id = :id and p.is_active"
            ),
            {"id": product_id},
        )
        .mappings()
        .first()
    )


def _pack_size(header: Mapping[str, Any]) -> Decimal | None:
    if header["base_quantity"] is None:
        return None
    return header["base_quantity"] * header["pack_count"]


def _concrete_quantity(item: Item, header: Mapping[str, Any]) -> tuple[Decimal, Unit]:
    """Quantity in the base unit of the requested product, so the optimizer buys those packs."""
    size = _pack_size(header)
    if size is None or header["base_unit"] is None:
        return item.quantity, Unit.UD
    return item.quantity * size, Unit(header["base_unit"])


def _collect(
    chosen: Sequence[tuple[Mapping[str, Any], Product]], brands: Brands
) -> tuple[
    dict[int, list[Product]],
    dict[int, str],
    dict[int, int | None],
    dict[int, str | None],
    dict[int, str | None],
]:
    products: dict[int, list[Product]] = {}
    names: dict[int, str] = {}
    canonicals: dict[int, int | None] = {}
    brand_names: dict[int, str | None] = {}
    images: dict[int, str | None] = {}
    for row, product in chosen:
        products.setdefault(row["zone_id"], []).append(product)
        product_id = row["product_id"]
        names[product_id] = row["name"]
        canonicals[product_id] = row["canonical_id"]
        brand_names[product_id] = brands.brand_for(row["name"])
        images[product_id] = row["image_url"]
    return (
        {zone: tuple(items) for zone, items in products.items()},
        names,
        canonicals,
        brand_names,
        images,
    )


def _candidates(
    rows: Sequence[Mapping[str, Any]],
    item: Item,
    brands: Brands,
    dimension_unit: str | None,
    canonical_id: int,
) -> list[tuple[Mapping[str, Any], Product]]:
    brand_terms = brands.terms(item.brand) if item.brand else None
    chosen: list[tuple[Mapping[str, Any], Product]] = []
    for row in rows:
        product = _product(row, canonical_id, dimension_unit, brands)
        if product is None:
            continue
        if not item.private_label_ok and product.is_private_label:
            continue
        if brand_terms is not None and not matches_brand(row["name"], brand_terms):
            continue
        chosen.append((row, product))
    return chosen


def _product_rows(session: Session, zone_ids: set[int]) -> list[Mapping[str, Any]]:
    """Active products with a current price in each zone, with their canonical category."""
    if not zone_ids:
        return []
    return list(
        session.execute(
            text(
                """
                select cp.id as product_id, cp.chain_id, cp.name, cp.image_url,
                       cp.base_quantity, cp.base_unit, cp.pack_count,
                       cp.canonical_id, canon.variant_key,
                       pc.zone_id, pc.price,
                       array(
                           select ancestor_id from category_closure
                           where descendant_id =
                               coalesce(canon.category_id, cc.category_id)
                       ) as ancestor_ids
                from chain_product cp
                left join canonical_product canon on canon.id = cp.canonical_id
                left join chain_category cc on cc.id = cp.chain_category_id
                join chain_product_zone cpz
                  on cpz.chain_product_id = cp.id and cpz.is_available
                join price_current pc
                  on pc.chain_product_id = cp.id and pc.zone_id = cpz.zone_id
                where cp.is_active
                  and cpz.zone_id in :zones
                order by cp.id, pc.zone_id
                """
            ).bindparams(bindparam("zones", expanding=True)),
            {"zones": sorted(zone_ids)},
        ).mappings()
    )


def _product(
    row: Mapping[str, Any],
    canonical_id: int,
    line_base_unit: str | None,
    brands: Brands,
) -> Product | None:
    """Optimizer product, or None when it cannot satisfy the line or has no size to compare by."""
    quantity, unit = row["base_quantity"], row["base_unit"]
    if quantity is None or unit is None:
        return None
    line_dimension = _DIMENSIONS.get(line_base_unit or "")
    product_dimension = _DIMENSIONS.get(unit)
    if line_dimension and product_dimension and line_dimension != product_dimension:
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


def _default_quantity(
    item: Item,
    category: CategoryInfo,
    rows: Sequence[tuple[Mapping[str, Any], Product]],
) -> Decimal | None:
    """The leaf's usual quantity, or the median pack for a counted line of a weighed leaf.

    A line without a quantity ("pollo") counts units of a product sold by kg or l: its candidate
    products give the typical pack, and the optimizer compares their price per kilo within the
    normal band (decision 0010).
    """
    if category.default_quantity is not None:
        return category.default_quantity
    if item.unit is not Unit.UD or category.base_unit not in (BaseUnit.KG.value, BaseUnit.L.value):
        return None
    quantities = sorted({row["product_id"]: row["base_quantity"] for row, _ in rows}.values())
    if not quantities:
        return None
    # The lower median is one of the sizes actually on sale when the count is even.
    return quantities[(len(quantities) - 1) // 2]


def _requested_variants(item: Item) -> frozenset[str]:
    """The variant keys of the line: explicit ones, or the variants its text names."""
    if item.variants is not None:
        return frozenset(item.variants)
    line_words = words(item.text)
    return frozenset(term.key for term in _variant_terms() if _contains_any(line_words, term.forms))


def _with_variant_names(
    rows: Sequence[Mapping[str, Any]], requested: Sequence[str]
) -> list[Mapping[str, Any]]:
    """Keep the products matching every non-canonical variant named in the line, when sold.

    "pasta integral" keeps the wholemeal pasta; a variant no product carries ("huevos eco")
    filters nothing.
    """
    terms = _term_by_key()
    kept = list(rows)
    for key in sorted(requested):
        forms = terms[key].forms
        matching = [row for row in kept if _contains_any(words(row["name"]), forms)]
        kept = matching or kept
    return kept


def _content_words(item: Item, category: CategoryInfo, brands: Brands) -> tuple[str, ...]:
    """What the line says beyond its category, its variants and its brand.

    Short words, numbers, units, connectors and the words already handled by the category
    name, the variant filter or the brand filter cannot narrow the products of the category.
    """
    excluded = set(words(category.name))
    excluded.update(R.CONNECTORS)
    excluded.update(R.NUMBER_WORDS)
    excluded.update(R.FRACTION_WORDS)
    excluded.update(term.form for term in R.UNITS)
    for term in _variant_terms():
        for form in term.forms:
            excluded.update(form)
    if item.brand:
        for brand_term in brands.terms(item.brand):
            excluded.update(words(brand_term))
    content: list[str] = []
    for word in words(item.text):
        if len(word) < 3 or any(char.isdigit() for char in word):
            continue
        if not any(char.isalpha() for char in word):
            continue
        if any(same_word(word, excluded_word) for excluded_word in excluded):
            continue
        content.append(word)
    return tuple(content)


def _with_line_words(
    rows: Sequence[Mapping[str, Any]], content_words: Sequence[str]
) -> list[Mapping[str, Any]]:
    """Keep the products whose name contains a line word, when only some of them do.

    A word no product or every product names narrows nothing, so a line never loses its
    candidates to a word that is not on the shelf ("yogur grande").
    """
    kept = list(rows)
    for word in content_words:
        matching = [row for row in kept if _contains_form(words(row["name"]), (word,))]
        if matching and len(matching) < len(kept):
            kept = matching
    return kept


def _is_plain(key: str) -> bool:
    """Whether a canonical variant key is accepted by a line that requests no variant."""
    term = _term_by_key().get(key)
    return term is not None and term.plain


def _variant_keys(raw: str | None) -> frozenset[str]:
    """The variant keys stored in a canonical product, sorted and `|`-joined."""
    return frozenset(key for key in (raw or "").split("|") if key)


@lru_cache(maxsize=1)
def _variant_terms() -> tuple[VariantTerm, ...]:
    """Every general variant, read from the seed once per process."""
    data = json.loads(VARIANTS_FILE.read_text(encoding="utf-8"))
    return tuple(
        VariantTerm(
            key=variant["key"],
            forms=tuple(
                words(form)
                for form in variant.get("forms") or [variant.get("name", variant["key"])]
            ),
            canonical=bool(variant.get("canonical", False)),
            plain=bool(variant.get("plain", False)),
        )
        for variant in data.get("variants", [])
    )


@lru_cache(maxsize=1)
def _term_by_key() -> dict[str, VariantTerm]:
    return {term.key: term for term in _variant_terms()}


def variant_keys() -> frozenset[str]:
    """The keys of every shipped general variant, for request validation."""
    return frozenset(term.key for term in _variant_terms())


def _contains_any(haystack: tuple[str, ...], forms: Iterable[tuple[str, ...]]) -> bool:
    """True when any form appears as whole words of `haystack`, plural tolerated."""
    return any(_contains_form(haystack, form) for form in forms)


def _contains_form(haystack: tuple[str, ...], form: tuple[str, ...]) -> bool:
    """True when `form` appears as a run of whole words of `haystack`."""
    if not form or len(form) > len(haystack):
        return False
    return any(
        all(same_word(haystack[start + offset], word) for offset, word in enumerate(form))
        for start in range(len(haystack) - len(form) + 1)
    )
