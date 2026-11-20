"""Taxonomy expansion for unmatched chain products (iteration 15, ADR 0022/0024).

After deterministic rules and the LLM verifier (`run --policy llm`) assign every product that
fits an existing canonical, the remaining products fall into two clean buckets:

1. Products that belong to an existing leaf category but carry a variant not yet present in
   `canonical_product` (for example ``Maíz dulce en conserva — sin azúcar``).
2. Products that represent a genuinely new leaf not yet present in the seed taxonomy (for
   example ``Kombucha`` under ``Refrescos`` or ``Pasta de legumbres`` under ``Pasta``).

This module groups remaining unmatched products by chain section, asks an `LLMProvider` to place
each product into an existing leaf category or a clean generic Spanish leaf under one of the
existing level-2 taxonomy groups, and persists every new leaf as a reversible
`catalog_leaf_proposal` row (ADR 0022).
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.agent.catalog_executors import nearest_canonicals
from smart_basket.agent.catalog_policies import DEFAULT_RETRY_DELAYS, _product_variants
from smart_basket.llm.base import LLMError, LLMProvider

CATALOG_EXPAND_SYSTEM_ES = (
    "Eres el agente de catálogo de Smart Basket (supermercados en España). "
    "Recibes los productos restantes de una sección de una cadena que aún no tienen producto "
    "canónico asignado, junto con las categorías hoja (nivel 3) más cercanas y la lista cerrada "
    "de grupos padre (nivel 2). Clasifica el 100% de los productos con precisión:\n"
    "1. Usa mode='existing_category_variant' SOLO si el producto pertenece exactamente a una de "
    "las categorías hoja existentes listadas (mismo tipo de producto, p.ej. con una variante "
    "nueva como sin azúcar, sin sal, reducido en sal, picante o sabor distinto).\n"
    "2. Usa mode='new_leaf' cuando el producto es un tipo de producto distinto que no existe aún "
    "en las hojas listadas (p.ej. 'Queso parmesano', 'Kombucha', 'Pasta de legumbres'). "
    "Pon un `leaf_name` genérico, limpio y en español SIN marca ni peso/formato. Agrupa "
    "productos equivalentes de esta lista bajo el MISMO `leaf_name` exacto. Elige "
    "`parent_group_id` obligatoriamente de la lista de grupos nivel 2.\n"
    "Responde SOLO con el JSON pedido."
)


def expand_catalog_taxonomy(
    session: Session,
    provider_factory: Callable[[], LLMProvider],
    *,
    chain_code: str | None = None,
    max_workers: int = 8,
    chunk_size: int = 20,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> dict[str, int]:
    """Classify all remaining unmatched active products by adding variants and reversible leaves.

    `provider_factory` is called once per worker thread so HTTP clients stay thread-local.
    """
    groups = list(
        session.execute(
            text(
                "select g.id, g.key, g.name, p.name as section_name "
                "from category g left join category p on p.id = g.parent_id "
                "where g.level = 2 order by p.name, g.name"
            )
        ).mappings()
    )
    if not groups:
        return {"assigned": 0, "new_leaves": 0, "new_variants": 0}
    group_ids = [int(g["id"]) for g in groups]
    groups_text = "\n".join(f"  {g['id']}: {g['section_name']} > {g['name']}" for g in groups)

    where = ["cp.canonical_id is null", "cp.is_active"]
    params: dict[str, Any] = {}
    if chain_code is not None:
        where.append("ch.code = :chain")
        params["chain"] = chain_code
    unmatched = list(
        session.execute(
            text(
                "select cp.id, cp.name, cp.base_unit, cp.chain_category_id, "
                "  cc.name as section_l2, pcc.name as section_l1, "
                "  cp.embedding::real[] as embedding "
                "from chain_product cp "
                "join chain ch on ch.id = cp.chain_id "
                "left join chain_category cc on cc.id = cp.chain_category_id "
                "left join chain_category pcc "
                "  on pcc.chain_id = cc.chain_id and pcc.code = cc.parent_code "
                f"where {' and '.join(where)} "
                "order by cp.chain_category_id, cp.id"
            ),
            params,
        ).mappings()
    )
    if not unmatched:
        return {"assigned": 0, "new_leaves": 0, "new_variants": 0}

    by_cat: dict[tuple[Any, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in unmatched:
        bucket_key = (
            row["chain_category_id"],
            row["section_l1"] or "",
            row["section_l2"] or "sin categoría",
        )
        by_cat[bucket_key].append(dict(row))

    buckets = []
    for (_, l1, l2), items in by_cat.items():
        keys: list[str] = []
        seen_keys: set[str] = set()
        for item in items:
            if item["embedding"] is None:
                continue
            for match in nearest_canonicals(session, item["embedding"], top_k=3):
                if match.category_key not in seen_keys:
                    seen_keys.add(match.category_key)
                    keys.append(match.category_key)
        existing_cats = []
        if keys:
            rows = session.execute(
                text(
                    "select c.id, c.key, c.name, c.base_unit, p.name as parent_name "
                    "from category c left join category p on p.id = c.parent_id "
                    "where c.key = any(:keys)"
                ),
                {"keys": keys[:12]},
            ).mappings()
            existing_cats = [dict(r) for r in rows]
        buckets.append((l1, l2, items, existing_cats))

    def _classify_bucket(
        bucket: tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]],
    ) -> dict[int, dict[str, Any]]:
        l1, l2, items, existing_cats = bucket
        provider = provider_factory()
        ex_ids = {int(c["id"]) for c in existing_cats}
        ex_text = (
            "\n".join(
                f"  {c['id']}: {c['name']} (grupo: {c['parent_name']})" for c in existing_cats
            )
            or "  (ninguna)"
        )
        decisions: dict[int, dict[str, Any]] = {}
        for start in range(0, len(items), chunk_size):
            chunk = items[start : start + chunk_size]
            prod_lines = []
            for it in chunk:
                vk = "|".join(sorted(_product_variants(it["name"]))) or "ninguna"
                prod_lines.append(f"  - id={it['id']}: {it['name']} [variantes_detectadas={vk}]")
            user_prompt = (
                f"SECCIÓN DE CADENA: {l1} > {l2}\n\n"
                f"CATEGORÍAS HOJA EXISTENTES MÁS CERCANAS:\n{ex_text}\n\n"
                f"GRUPOS PADRE NIVEL 2 (para mode='new_leaf'):\n{groups_text}\n\n"
                f"PRODUCTOS A CLASIFICAR ({len(chunk)}):\n" + "\n".join(prod_lines)
            )
            schema = _expand_schema()
            response = _generate_with_retry(provider, user_prompt, schema, retry_delays)
            for entry in (response or {}).get("items", ()):
                pid = int(entry["product_id"])
                if (
                    entry.get("mode") == "existing_category_variant"
                    and int(entry.get("existing_category_id") or 0) in ex_ids
                ):
                    decisions[pid] = entry
                else:
                    parent = int(entry.get("parent_group_id") or 0)
                    if parent not in group_ids:
                        parent = group_ids[0]
                    decisions[pid] = {
                        "product_id": pid,
                        "mode": "new_leaf",
                        "leaf_name": _clean_leaf_name(entry.get("leaf_name") or l2),
                        "parent_group_id": parent,
                    }
        return decisions

    all_decisions: dict[int, dict[str, Any]] = {}
    workers = max(1, min(max_workers, len(buckets)))
    if workers == 1:
        for bucket in buckets:
            all_decisions.update(_classify_bucket(bucket))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for decs in pool.map(_classify_bucket, buckets):
                all_decisions.update(decs)

    return _persist_expansions(session, unmatched, all_decisions, group_ids[0])


def _persist_expansions(
    session: Session,
    unmatched: list[Any],
    decisions: dict[int, dict[str, Any]],
    fallback_group_id: int,
) -> dict[str, int]:
    leaf_cache: dict[tuple[int | None, str], tuple[int, str, str]] = {}
    for row in session.execute(
        text(
            "select id, parent_id, lower(name) as lname, key, base_unit "
            "from category where level = 3"
        )
    ).mappings():
        leaf_cache[(row["parent_id"], row["lname"])] = (
            int(row["id"]),
            row["key"],
            row["base_unit"],
        )

    existing_keys = set(session.execute(text("select key from category")).scalars())
    cat_info = {
        int(r["id"]): (r["key"], r["name"], r["base_unit"])
        for r in session.execute(text("select id, key, name, base_unit from category")).mappings()
    }

    new_leaves = 0
    new_variants = 0
    assigned = 0
    leaf_products: dict[str, list[int]] = defaultdict(list)

    for item in unmatched:
        pid = int(item["id"])
        dec = decisions.get(pid) or {
            "mode": "new_leaf",
            "leaf_name": _clean_leaf_name(item["section_l2"] or "Producto vario"),
            "parent_group_id": fallback_group_id,
        }
        vk = "|".join(sorted(_product_variants(item["name"])))
        unit = item["base_unit"] or "ud"

        if dec["mode"] == "existing_category_variant":
            cat_id = int(dec["existing_category_id"])
            cat_key, cat_name, cat_unit = cat_info[cat_id]
        else:
            parent_id = int(dec["parent_group_id"])
            lname = _clean_leaf_name(dec["leaf_name"])
            cache_key = (parent_id, lname.lower())
            if cache_key in leaf_cache:
                cat_id, cat_key, cat_unit = leaf_cache[cache_key]
                cat_name = lname
            else:
                cat_key = _unique_key(existing_keys, _slugify(lname))
                existing_keys.add(cat_key)
                cat_unit = unit
                cat_id = int(
                    session.execute(
                        text(
                            "insert into category (key, name, level, parent_id, base_unit) "
                            "values (:key, :name, 3, :parent, :unit) returning id"
                        ),
                        {"key": cat_key, "name": lname, "parent": parent_id, "unit": cat_unit},
                    ).scalar_one()
                )
                session.execute(
                    text(
                        "insert into category_closure (ancestor_id, descendant_id, depth) "
                        "values (:cat, :cat, 0)"
                    ),
                    {"cat": cat_id},
                )
                session.execute(
                    text(
                        "insert into category_closure (ancestor_id, descendant_id, depth) "
                        "select ancestor_id, :cat, depth + 1 "
                        "from category_closure where descendant_id = :parent"
                    ),
                    {"cat": cat_id, "parent": parent_id},
                )
                leaf_cache[cache_key] = (cat_id, cat_key, cat_unit)
                cat_info[cat_id] = (cat_key, lname, cat_unit)
                cat_name = lname
                new_leaves += 1
            leaf_products[cat_key].append(pid)

        can_id = session.execute(
            text(
                "select id from canonical_product "
                "where category_id = :cat and variant_key = :vk and merged_into is null limit 1"
            ),
            {"cat": cat_id, "vk": vk},
        ).scalar_one_or_none()
        if can_id is None:
            can_name = f"{cat_name} — {_variant_label(vk)}" if vk else cat_name
            can_id = int(
                session.execute(
                    text(
                        "insert into canonical_product (category_id, name, variant_key, base_unit) "
                        "values (:cat, :name, :vk, :unit) returning id"
                    ),
                    {"cat": cat_id, "name": can_name, "vk": vk, "unit": cat_unit},
                ).scalar_one()
            )
            if dec["mode"] == "existing_category_variant":
                new_variants += 1

        session.execute(
            text(
                "update chain_product "
                "set canonical_id = :can, match_method = 'embedding', match_confidence = 0.90 "
                "where id = :pid and canonical_id is null"
            ),
            {"can": can_id, "pid": pid},
        )
        session.execute(
            text(
                "insert into product_match (chain_product_id, canonical_id, method) "
                "values (:pid, :can, 'embedding')"
            ),
            {"pid": pid, "can": can_id},
        )
        session.execute(
            text(
                "update match_review set status = 'accepted', resolved_at = now() "
                "where chain_product_id = :pid and status = 'pending'"
            ),
            {"pid": pid},
        )
        assigned += 1

    signals_json = json.dumps(["embedding", "chain_category", "llm_taxonomy"])
    for cat_key, pids in leaf_products.items():
        session.execute(
            text(
                "insert into catalog_leaf_proposal "
                "  (category_key, category_name, parent_category_id, product_ids_json, "
                "   signals_json, status) "
                "select key, name, parent_id, cast(:pids as jsonb), "
                "  cast(:signals as jsonb), 'applied' "
                "from category where key = :key"
            ),
            {"key": cat_key, "pids": json.dumps(pids), "signals": signals_json},
        )

    return {"assigned": assigned, "new_leaves": new_leaves, "new_variants": new_variants}


def _generate_with_retry(
    provider: LLMProvider,
    user_prompt: str,
    schema: dict[str, Any],
    retry_delays: tuple[float, ...],
) -> dict[str, Any]:
    failure: Exception | None = None
    for delay in (0.0, *retry_delays):
        if delay > 0:
            time.sleep(delay)
        try:
            return provider.generate_json(CATALOG_EXPAND_SYSTEM_ES, user_prompt, schema)
        except LLMError as exc:
            if "429" not in str(exc):
                raise
            failure = exc
    assert failure is not None
    raise failure


def _expand_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "mode": {
                            "type": "string",
                            "enum": ["existing_category_variant", "new_leaf"],
                        },
                        "existing_category_id": {"type": "integer"},
                        "leaf_name": {"type": "string"},
                        "parent_group_id": {"type": "integer"},
                    },
                    "required": ["product_id", "mode", "parent_group_id"],
                },
            }
        },
        "required": ["items"],
    }


def _slugify(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_str).strip("_") or "hoja"


def _unique_key(existing: set[str], base: str) -> str:
    key = base
    suffix = 2
    while key in existing:
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def _clean_leaf_name(name: str) -> str:
    cleaned = " ".join(str(name).strip().split())
    return (cleaned[0].upper() + cleaned[1:]) if cleaned else "Producto vario"


def _variant_label(vk: str) -> str:
    if not vk:
        return ""
    parts = [
        ("sabor " + k[6:].replace("_", " ")) if k.startswith("sabor:") else k.replace("_", " ")
        for k in vk.split("|")
    ]
    return ", ".join(parts)
