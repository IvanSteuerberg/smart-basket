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
from smart_basket.agent.catalog_policies import (
    DEFAULT_RETRY_DELAYS,
    _preprocessor,
    _product_variants,
    mutex_compatible,
)
from smart_basket.llm.base import LLMError, LLMProvider
from smart_basket.preprocessor.text import fold, tokenize

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
    "3. Devuelve `variant_key` limpio en minúsculas con `|` como separador (p.ej. `sin_azucar`, "
    "`sabor:pollo`, `sabor:ahumado`) o `''` si no hay variante. NUNCA incluyas marcas comerciales "
    "(Oscar Mayer, Haribo, Gallina Blanca, Halls, Heinz...) ni envases (bolsa, blister) dentro de "
    "`variant_key`, ni repitas un sabor que ya aparece en el nombre de la categoría.\n"
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

    all_leaf_rows = session.execute(
        text(
            "select c.id, c.key, c.name, c.base_unit, p.name as parent_name "
            "from category c left join category p on p.id = c.parent_id "
            "where c.level = 3"
        )
    ).mappings()
    leaf_by_key: dict[str, dict[str, Any]] = {}
    leaf_by_id: dict[int, dict[str, Any]] = {}
    for r in all_leaf_rows:
        d = dict(r)
        leaf_by_key[d["key"]] = d
        leaf_by_id[int(d["id"])] = d

    by_cat: dict[tuple[Any, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in unmatched:
        item = dict(row)
        near_keys: list[str] = []
        if item["embedding"] is not None:
            for match in nearest_canonicals(session, item["embedding"], top_k=4):
                if match.category_key not in near_keys and match.category_key in leaf_by_key:
                    near_keys.append(match.category_key)
        item["near_keys"] = near_keys
        bucket_key = (
            row["chain_category_id"],
            row["section_l1"] or "",
            row["section_l2"] or "sin categoría",
        )
        by_cat[bucket_key].append(item)

    buckets = []
    for (_, l1, l2), items in by_cat.items():
        buckets.append((l1, l2, items))

    def _classify_bucket(
        bucket: tuple[str, str, list[dict[str, Any]]],
    ) -> dict[int, dict[str, Any]]:
        l1, l2, items = bucket
        provider = provider_factory()
        decisions: dict[int, dict[str, Any]] = {}
        for start in range(0, len(items), chunk_size):
            chunk = items[start : start + chunk_size]
            chunk_keys: list[str] = []
            seen_ck: set[str] = set()
            for it in chunk:
                for ck in it.get("near_keys", ()):
                    if ck not in seen_ck:
                        seen_ck.add(ck)
                        chunk_keys.append(ck)
            chunk_cats = [leaf_by_key[ck] for ck in chunk_keys[:32] if ck in leaf_by_key]
            ex_text = (
                "\n".join(
                    f"  {c['id']}: {c['name']} (grupo: {c['parent_name']})" for c in chunk_cats
                )
                or "  (ninguna)"
            )
            prod_lines = []
            for it in chunk:
                vk = "|".join(sorted(_product_variants(it["name"]))) or "ninguna"
                near_hint = ", ".join(
                    f"{leaf_by_key[ck]['id']}:{leaf_by_key[ck]['name']}"
                    for ck in it.get("near_keys", ())[:3]
                    if ck in leaf_by_key
                )
                hint_suffix = f" [cercanas={near_hint}]" if near_hint else ""
                prod_lines.append(
                    f"  - id={it['id']}: {it['name']} [variantes_detectadas={vk}]{hint_suffix}"
                )
            user_prompt = (
                f"SECCIÓN DE CADENA: {l1} > {l2}\n\n"
                f"CATEGORÍAS HOJA EXISTENTES MÁS CERCANAS:\n{ex_text}\n\n"
                f"GRUPOS PADRE NIVEL 2 (para mode='new_leaf'):\n{groups_text}\n\n"
                f"PRODUCTOS A CLASIFICAR ({len(chunk)}):\n" + "\n".join(prod_lines)
            )
            schema = _expand_schema()
            response = _generate_with_retry(provider, user_prompt, schema, retry_delays)
            by_pid = {int(it["id"]): it for it in chunk}
            for entry in (response or {}).get("items", ()):
                pid = int(entry["product_id"])
                prod_item = by_pid.get(pid)
                pname = prod_item["name"] if prod_item else ""
                ex_id = int(entry.get("existing_category_id") or 0)
                if entry.get("mode") == "existing_category_variant" and ex_id in leaf_by_id:
                    decisions[pid] = {
                        "product_id": pid,
                        "mode": "existing_category_variant",
                        "existing_category_id": ex_id,
                        "leaf_name": _clean_leaf_name(
                            entry.get("leaf_name"), fallback_product_name=pname
                        ),
                        "parent_group_id": int(entry.get("parent_group_id") or group_ids[0]),
                        "variant_key": _clean_variant_key(entry.get("variant_key") or ""),
                    }
                else:
                    parent = int(entry.get("parent_group_id") or 0)
                    if parent not in group_ids:
                        parent = group_ids[0]
                    decisions[pid] = {
                        "product_id": pid,
                        "mode": "new_leaf",
                        "leaf_name": _clean_leaf_name(
                            entry.get("leaf_name"), fallback_product_name=pname
                        ),
                        "parent_group_id": parent,
                        "variant_key": _clean_variant_key(entry.get("variant_key") or ""),
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


_LEAF_CONNECTORS = frozenset(
    {"a", "al", "con", "de", "del", "e", "el", "en", "la", "las", "los", "para", "por", "y"}
)


def _singularize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("es") and token[-3] not in "aeiou":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "is", "us")):
        return token[:-1]
    return token


def _norm_leaf_key(name: str) -> str:
    tokens = sorted(
        {
            _singularize_token(t.key)
            for t in tokenize(name)
            if t.kind == "word" and t.key not in _LEAF_CONNECTORS
        }
    )
    return " ".join(tokens)


def _persist_expansions(
    session: Session,
    unmatched: list[Any],
    decisions: dict[int, dict[str, Any]],
    fallback_group_id: int,
) -> dict[str, int]:
    leaf_cache: dict[tuple[int | None, str], tuple[int, str, str, str]] = {}
    global_leaf_by_norm: dict[str, tuple[int, str, str, str]] = {}
    for row in session.execute(
        text(
            "select id, parent_id, name, lower(name) as lname, key, base_unit "
            "from category where level = 3 order by id asc"
        )
    ).mappings():
        entry = (int(row["id"]), row["key"], row["name"], row["base_unit"])
        leaf_cache[(row["parent_id"], row["lname"])] = entry
        norm = _norm_leaf_key(row["name"])
        if norm and norm not in global_leaf_by_norm:
            global_leaf_by_norm[norm] = entry

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
            "leaf_name": _clean_leaf_name(None, fallback_product_name=item["name"]),
            "parent_group_id": fallback_group_id,
        }
        raw_vk = dec.get("variant_key")
        if isinstance(raw_vk, str):
            vk = _clean_variant_key(raw_vk)
        else:
            vk = _clean_variant_key(
                "|".join(
                    sorted(k for k in _product_variants(item["name"]) if not k.startswith("sabor:"))
                )
            )
        unit = item["base_unit"] or "ud"

        use_existing = False
        if (
            dec["mode"] == "existing_category_variant"
            and int(dec.get("existing_category_id") or 0) in cat_info
        ):
            cand_id = int(dec["existing_category_id"])
            cand_key, cand_name, cand_unit = cat_info[cand_id]
            if (
                not _GENERIC_SECTION_PATTERNS.match(cand_name)
                and not _has_leaf_defect(cand_name)
                and mutex_compatible(item["name"], cand_name, vk)
            ):
                use_existing = True
                cat_id, cat_key, cat_name, cat_unit = cand_id, cand_key, cand_name, cand_unit

        if not use_existing:
            parent_id = int(dec.get("parent_group_id") or fallback_group_id)
            lname = _clean_leaf_name(dec.get("leaf_name"), fallback_product_name=item["name"])
            cache_key = (parent_id, lname.lower())
            norm_key = _norm_leaf_key(lname)
            if cache_key in leaf_cache:
                cat_id, cat_key, cat_name, cat_unit = leaf_cache[cache_key]
            elif norm_key and norm_key in global_leaf_by_norm:
                cat_id, cat_key, cat_name, cat_unit = global_leaf_by_norm[norm_key]
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
                entry = (cat_id, cat_key, lname, cat_unit)
                leaf_cache[cache_key] = entry
                if norm_key and norm_key not in global_leaf_by_norm:
                    global_leaf_by_norm[norm_key] = entry
                cat_info[cat_id] = (cat_key, lname, cat_unit)
                cat_name = lname
                new_leaves += 1
            leaf_products[cat_key].append(pid)

        can_id = session.execute(
            text(
                "select coalesce(merged_into, id) from canonical_product "
                "where category_id = :cat and variant_key = :vk "
                "order by (merged_into is null) desc, id asc limit 1"
            ),
            {"cat": cat_id, "vk": vk},
        ).scalar_one_or_none()
        if can_id is None:
            can_name = f"{cat_name} — {_variant_label(vk)}" if vk else cat_name
            can_id = int(
                session.execute(
                    text(
                        "insert into canonical_product (category_id, name, variant_key, base_unit) "
                        "values (:cat, :name, :vk, :unit) "
                        "on conflict (category_id, name, variant_key) do update "
                        "set base_unit = canonical_product.base_unit "
                        "returning coalesce(merged_into, id)"
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
                        "variant_key": {"type": "string"},
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


_GENERIC_SECTION_PATTERNS = re.compile(
    r"^(?:general|otros|sin\s+categor[ií]a|producto\s+vario|congelados?|frescos?|"
    r"folleto\b.*|.*\bgeneral)$",
    re.IGNORECASE,
)

_TRAILING_STOPWORDS = frozenset(
    {
        "de",
        "del",
        "con",
        "sin",
        "a",
        "en",
        "y",
        "e",
        "o",
        "u",
        "para",
        "por",
        "al",
        "el",
        "la",
        "sabor",
    }
)

_BANNED_BRAND_TOKENS = frozenset(
    {
        "actimel",
        "aguinaga",
        "ariel",
        "au",
        "babybel",
        "baileys",
        "bebe_seco",
        "black_label",
        "calciavena",
        "calcimel",
        "cancun",
        "chips_ahoy",
        "cointreau",
        "colacao",
        "cola_cao",
        "danet",
        "danone",
        "dodot",
        "dolce_gusto",
        "don_simon",
        "el_corte_ingles",
        "extrafino",
        "fairy",
        "fanta",
        "gallina_blanca",
        "gelli",
        "grefusa",
        "guinas",
        "gula",
        "gulas",
        "halls",
        "haribo",
        "heinz",
        "jetas",
        "kinder",
        "kit_kat",
        "kitkat",
        "lenor",
        "lindt",
        "lotus",
        "matchball",
        "matutano",
        "milka",
        "milsani",
        "nenuco",
        "nescafe",
        "nespresso",
        "nesquik",
        "nocilla",
        "nutella",
        "oreo",
        "oscar_mayer",
        "perfomance",
        "pescanova",
        "philadelphia",
        "quadritos",
        "red_bull",
        "red_label",
        "reina",
        "risi",
        "risketos",
        "spontex",
        "tassimo",
        "triskys",
        "up2fashion",
        "valor",
        "yarroz",
        "yatekomo",
        "yogomix",
    }
)


_BRAND_PHRASE_RE = re.compile(
    r"\b(?:el\s+corte\s+ingl[eé]s(?:\s+selection)?|el\s+obrador|up2fashion|"
    r"redondo\s+iglesias|home\s+creation|milsani|lacura|special|dodot|beb[eé]\s+seco|"
    r"nenuco|chips\s+ahoy|dolce\s+gusto|red\s+label|black\s+label|johnnie\s+walker)\b",
    re.IGNORECASE,
)


def _strip_brand_parentheticals(text_val: str) -> str:
    cleaned = re.sub(
        r"\s*\((?:yogomix|actimel[^)]*|babybel|dolce\s+gusto|nespresso)\)",
        "",
        text_val,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\btipo\s+babybel\b", "en porciones", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\bguinas(?:\s+de\s+aguinaga)?\b", "sucedáneo de angula", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\byarroz\b", "arroz con", cleaned, flags=re.IGNORECASE)
    cleaned = _BRAND_PHRASE_RE.sub("", cleaned)
    return " ".join(cleaned.split())


_LEADING_UPPER_BRAND_RE = re.compile(
    r"^(?:[A-ZÁÉÍÓÚÑ0-9&'.-]{2,}\s+){1,4}(?=[A-ZÁÉÍÓÚÑ][a-záéíóúñ])"
)


def _fallback_leaf_from_product(product_name: str) -> str:
    if not product_name:
        return "Producto de alimentación"
    stripped = _LEADING_UPPER_BRAND_RE.sub("", product_name.strip())
    stripped = _strip_brand_parentheticals(stripped)
    _, without_brand, _ = _preprocessor().find_brand(tokenize(stripped))
    words = [
        t.text
        for t in without_brand
        if t.kind == "word"
        and t.key not in _BANNED_BRAND_TOKENS
        and t.key not in {"pack", "ud", "uds", "kg", "gr", "cl", "ml", "l", "g", "u", "aprox"}
    ][:5]
    while words and fold(words[0]) in _TRAILING_STOPWORDS:
        words.pop(0)
    while words and fold(words[-1]) in _TRAILING_STOPWORDS:
        words.pop()
    phrase = " ".join(words).strip(" ,.-")
    return (phrase[0].upper() + phrase[1:]) if phrase else "Producto de alimentación"


def _has_leaf_defect(name: str) -> bool:
    tokens = [fold(w.strip("(),.-")) for w in name.split() if w.strip("(),.-")]
    if not tokens:
        return True
    if tokens[0] in _TRAILING_STOPWORDS or tokens[-1] in _TRAILING_STOPWORDS:
        return True
    if any(t in _BANNED_BRAND_TOKENS for t in tokens):
        return True
    return name.strip().lower() == "producto de alimentación"


def _clean_leaf_name(name: str | None, *, fallback_product_name: str = "") -> str:
    cleaned = _strip_brand_parentheticals(" ".join(str(name or "").strip().split()))
    if not cleaned or _GENERIC_SECTION_PATTERNS.match(cleaned) or _has_leaf_defect(cleaned):
        cleaned = _strip_brand_parentheticals(" ".join(str(name or "").strip().split()))
        words = [w for w in cleaned.split() if fold(w.strip("(),.-")) not in _BANNED_BRAND_TOKENS]
        while words and fold(words[0].strip("(),.-")) in _TRAILING_STOPWORDS:
            words.pop(0)
        while words and fold(words[-1].strip("(),.-")) in _TRAILING_STOPWORDS:
            words.pop()
        cleaned = " ".join(words)
    if not cleaned or _GENERIC_SECTION_PATTERNS.match(cleaned) or _has_leaf_defect(cleaned):
        cleaned = _fallback_leaf_from_product(fallback_product_name)
    _, without_brand, found_brand = _preprocessor().find_brand(tokenize(cleaned))
    if found_brand is not None and without_brand:
        words = [t.text for t in without_brand if t.key not in _BANNED_BRAND_TOKENS]
        while words and fold(words[0]) in _TRAILING_STOPWORDS:
            words.pop(0)
        while words and fold(words[-1]) in _TRAILING_STOPWORDS:
            words.pop()
        if words:
            cleaned = " ".join(words)
    return (cleaned[0].upper() + cleaned[1:]) if cleaned else "Producto de alimentación"


def _clean_variant_key(raw_vk: str) -> str:
    if not raw_vk:
        return ""
    kept: set[str] = set()
    for part in raw_vk.split("|"):
        p = part.strip().lower().replace(" ", "_")
        if not p:
            continue
        bare = p[6:] if p.startswith("sabor:") else p
        if bare in _BANNED_BRAND_TOKENS:
            continue
        if any(f"_{b}_" in f"_{bare}_" for b in _BANNED_BRAND_TOKENS):
            continue
        kept.add(p)
    return "|".join(sorted(kept))


def _variant_label(vk: str) -> str:
    if not vk:
        return ""
    parts = [
        ("sabor " + k[6:].replace("_", " ")) if k.startswith("sabor:") else k.replace("_", " ")
        for k in vk.split("|")
    ]
    return ", ".join(parts)
