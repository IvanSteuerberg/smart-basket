"""Load the seed taxonomy, chains, brands and zones into the transactional schema.

The load is idempotent: rows are upserted by their natural keys, the category closure is rebuilt
from scratch and categories or brands that disappear from the file are kept and reported as
stale.
"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.seed.models import (
    BrandsFile,
    ChainCategoriesFile,
    ChainsFile,
    TaxonomyFile,
    ZoneKind,
    validate_seed,
)

TAXONOMY_FILE = "taxonomy_es.json"
CHAINS_FILE = "chains_es.json"
BRANDS_FILE = "brands_es.json"
CHAIN_CATEGORIES_DIR = "chain_categories"

#: Kind and code of the zone the loader creates for the whole chain.
CHAIN_WIDE_KIND = "chain"
CHAIN_WIDE_CODE = "all"


@dataclass
class TableCounts:
    """How many rows a table received on this load."""

    inserted: int = 0
    updated: int = 0


@dataclass
class SeedReport:
    """Result of `load_seed`."""

    chain: TableCounts = field(default_factory=TableCounts)
    zone: TableCounts = field(default_factory=TableCounts)
    category: TableCounts = field(default_factory=TableCounts)
    category_closure: TableCounts = field(default_factory=TableCounts)
    chain_category: TableCounts = field(default_factory=TableCounts)
    brand: TableCounts = field(default_factory=TableCounts)
    stale_categories: list[str] = field(default_factory=list)
    stale_brands: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"{name}: {counts.inserted} inserted, {counts.updated} updated"
            for name, counts in [
                ("chain", self.chain),
                ("zone", self.zone),
                ("category", self.category),
                ("category_closure", self.category_closure),
                ("chain_category", self.chain_category),
                ("brand", self.brand),
            ]
        ]
        stale = ", ".join(self.stale_categories) if self.stale_categories else "none"
        lines.append(f"stale categories: {stale}")
        stale = ", ".join(self.stale_brands) if self.stale_brands else "none"
        lines.append(f"stale brands: {stale}")
        return "\n".join(lines)


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"seed file not found: {path}")
    return path.read_text(encoding="utf-8")


def _count(counts: TableCounts, inserted: bool) -> None:
    if inserted:
        counts.inserted += 1
    else:
        counts.updated += 1


def load_seed(session: Session, data_dir: Path) -> SeedReport:
    """Validate and load the seed files of `data_dir` inside the session's transaction.

    The caller commits (or rolls back) the transaction. Files are validated before any SQL
    runs, so an invalid seed leaves the database untouched.
    """
    taxonomy = TaxonomyFile.model_validate_json(_read(data_dir / TAXONOMY_FILE))
    chains = ChainsFile.model_validate_json(_read(data_dir / CHAINS_FILE))
    brands = BrandsFile.model_validate_json(_read(data_dir / BRANDS_FILE))
    mapping_dir = data_dir / CHAIN_CATEGORIES_DIR
    mappings = {
        path.stem: ChainCategoriesFile.model_validate_json(_read(path))
        for path in sorted(mapping_dir.glob("*.json"))
    }
    validate_seed(taxonomy, chains, mappings, brands)

    report = SeedReport()
    chain_ids: dict[str, int] = {}

    for chain in chains.chains:
        row = session.execute(
            text(
                "insert into chain (code, name) values (:code, :name) "
                "on conflict (code) do update set name = excluded.name "
                "returning id, (xmax = 0) as inserted"
            ),
            {"code": chain.code, "name": chain.name},
        ).one()
        chain_ids[chain.code] = row.id
        _count(report.chain, row.inserted)

        chain_wide = None
        for zone in chain.zones:
            if zone.kind is ZoneKind.CHAIN and zone.code == CHAIN_WIDE_CODE:
                chain_wide = zone
                continue
            _upsert_zone(
                session, report.zone, chain_ids[chain.code], zone.kind, zone.code, zone.name
            )
        _upsert_zone(
            session,
            report.zone,
            chain_ids[chain.code],
            CHAIN_WIDE_KIND,
            CHAIN_WIDE_CODE,
            chain_wide.name if chain_wide else None,
        )

    incoming_brands = {brand.name for brand in brands.brands}
    for brand in brands.brands:
        owner_chain_id = (
            chain_ids[brand.private_label_of] if brand.private_label_of is not None else None
        )
        row = session.execute(
            text(
                "insert into brand "
                "(name, is_private_label, owner_chain_id, aliases, implies_category, "
                "match_name) "
                "values (:name, :is_private_label, :owner_chain_id, :aliases, :implies, "
                ":match_name) "
                "on conflict (name) do update set "
                "is_private_label = excluded.is_private_label, "
                "owner_chain_id = excluded.owner_chain_id, aliases = excluded.aliases, "
                "implies_category = excluded.implies_category, "
                "match_name = excluded.match_name "
                "returning (xmax = 0) as inserted"
            ),
            {
                "name": brand.name,
                "is_private_label": brand.private_label_of is not None,
                "owner_chain_id": owner_chain_id,
                "aliases": brand.aliases,
                "implies": brand.implies,
                "match_name": brand.match_name,
            },
        ).one()
        _count(report.brand, row.inserted)

    existing_brands = set(session.execute(text("select name from brand")).scalars())
    report.stale_brands = sorted(existing_brands - incoming_brands)

    rows = taxonomy.rows()
    incoming_keys = {category.key for category in rows}

    # `category` is unique on (parent_id, name) besides `key`. A key renamed in the file while
    # keeping its name and parent would collide with the old row, which is stale: detach the
    # stale row first so the upsert goes through.
    category_ids: dict[str, int] = {}
    stale_at: dict[tuple[int | None, str], list[tuple[int, str]]] = {}
    for existing in session.execute(text("select id, key, name, parent_id from category")):
        category_ids[existing.key] = existing.id
        if existing.key not in incoming_keys:
            stale_at.setdefault((existing.parent_id, existing.name), []).append(
                (existing.id, existing.key)
            )

    for category in rows:
        parent_id = category_ids.get(category.parent_key)
        for stale_id, stale_key in stale_at.pop((parent_id, category.name), []):
            session.execute(
                text("update category set name = :name where id = :id"),
                {"name": f"{category.name} (obsoleta {stale_key})", "id": stale_id},
            )
        row = session.execute(
            text(
                "insert into category "
                "(key, name, parent_id, level, base_unit, default_quantity, forms, is_vague) "
                "values (:key, :name, (select id from category where key = :parent_key), "
                ":level, :base_unit, :default_quantity, :forms, :is_vague) "
                "on conflict (key) do update set "
                "name = excluded.name, parent_id = excluded.parent_id, level = excluded.level, "
                "base_unit = excluded.base_unit, "
                "default_quantity = excluded.default_quantity, forms = excluded.forms, "
                "is_vague = excluded.is_vague "
                "returning id, (xmax = 0) as inserted"
            ),
            {
                "key": category.key,
                "name": category.name,
                "parent_key": category.parent_key,
                "level": category.level,
                "base_unit": category.base_unit.value if category.base_unit else None,
                "default_quantity": category.default_quantity,
                "forms": category.forms,
                "is_vague": category.is_vague,
            },
        ).one()
        category_ids[category.key] = row.id
        _count(report.category, row.inserted)

    existing = set(session.execute(text("select key from category")).scalars())
    report.stale_categories = sorted(existing - incoming_keys)
    # Stale categories are kept (canonical products may reference them) but must not feed the
    # preprocessor lexicon, which uses every category with forms.
    if report.stale_categories:
        session.execute(
            text("update category set forms = '{}' where key = any(:keys)"),
            {"keys": report.stale_categories},
        )

    # The closure is derived data: drop it and rebuild every (ancestor, descendant, depth).
    session.execute(text("delete from category_closure"))
    report.category_closure.inserted = session.execute(
        text(
            "with recursive tree as ("
            "  select id as ancestor_id, id as descendant_id, 0::smallint as depth"
            "  from category"
            "  union all"
            "  select t.ancestor_id, c.id, (t.depth + 1)::smallint"
            "  from tree t join category c on c.parent_id = t.descendant_id"
            ") "
            "insert into category_closure (ancestor_id, descendant_id, depth) "
            "select ancestor_id, descendant_id, depth from tree"
        )
    ).rowcount

    for mapping in mappings.values():
        for category in mapping.categories:
            row = session.execute(
                text(
                    "insert into chain_category "
                    "(chain_id, code, name, parent_code, category_id) "
                    "values (:chain_id, :code, :name, :parent_code, "
                    "(select id from category where key = :category)) "
                    "on conflict (chain_id, code) do update set "
                    "name = excluded.name, parent_code = excluded.parent_code, "
                    "category_id = excluded.category_id "
                    "returning (xmax = 0) as inserted"
                ),
                {
                    "chain_id": chain_ids[mapping.chain],
                    "code": category.code,
                    "name": category.name,
                    "parent_code": category.parent_code,
                    "category": category.category,
                },
            ).one()
            _count(report.chain_category, row.inserted)

    return report


def _upsert_zone(
    session: Session,
    counts: TableCounts,
    chain_id: int,
    kind: str,
    code: str,
    name: str | None,
) -> None:
    row = session.execute(
        text(
            "insert into zone (chain_id, kind, code, name) "
            "values (:chain_id, :kind, :code, :name) "
            "on conflict (chain_id, kind, code) do update set name = excluded.name "
            "returning (xmax = 0) as inserted"
        ),
        {"chain_id": chain_id, "kind": str(kind), "code": code, "name": name},
    ).one()
    _count(counts, row.inserted)
