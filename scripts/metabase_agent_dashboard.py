#!/usr/bin/env python3
"""Provision or update the Metabase dashboard for agent telemetry (ADR 0022).

Idempotent script using only the Python standard library. Connects to Metabase
via its REST API using environment variables:

    METABASE_URL       Base URL (default: http://127.0.0.1:3000)
    METABASE_EMAIL     Admin/editor email (required unless --dry-run)
    METABASE_PASSWORD  Account password (required unless --dry-run)
    METABASE_DB_NAME   Target Metabase database name (default: Smart Basket BI)

Usage:
    python scripts/metabase_agent_dashboard.py --dry-run
    python scripts/metabase_agent_dashboard.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DASHBOARD_TITLE = "Agente Recomendador (ADR 0022)"
DASHBOARD_DESCRIPTION = (
    "Telemetría del agente recomendador sobre bi.v_agent_run y bi.v_agent_step "
    "(acciones, confianza, latencia, modo degradado/fallback y ablación)."
)

CARDS: list[dict[str, Any]] = [
    {
        "name": "Acciones por tipo",
        "description": "Distribución de acciones elegidas por el agente (bi.v_agent_step).",
        "display": "bar",
        "size_x": 9,
        "size_y": 6,
        "row": 0,
        "col": 0,
        "sql": """
SELECT
    chosen_action AS accion,
    COUNT(*) AS pasos,
    ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2) AS porcentaje
FROM bi.v_agent_step
GROUP BY chosen_action
ORDER BY pasos DESC;
""".strip(),
    },
    {
        "name": "Confianza media y distribución por acción",
        "description": "Confianza media, p50, p95 y sobreescrituras por acción elegida.",
        "display": "table",
        "size_x": 9,
        "size_y": 6,
        "row": 0,
        "col": 9,
        "sql": """
SELECT
    chosen_action AS accion,
    COUNT(*) AS pasos,
    ROUND(AVG(confidence)::numeric, 4) AS confianza_media,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY confidence)::numeric, 4) AS confianza_p50,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY confidence)::numeric, 4) AS confianza_p95,
    SUM(CASE WHEN overridden THEN 1 ELSE 0 END) AS sobreescrituras
FROM bi.v_agent_step
WHERE confidence IS NOT NULL
GROUP BY chosen_action
ORDER BY pasos DESC;
""".strip(),
    },
    {
        "name": "Latencia p50/p95 por paso y por ejecución",
        "description": "Percentiles p50 y p95 de latencia por paso (latency_ms) y total (total_latency_ms).",
        "display": "table",
        "size_x": 9,
        "size_y": 5,
        "row": 6,
        "col": 0,
        "sql": """
SELECT
    'Por paso (ms)' AS nivel,
    COUNT(*) AS total,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms)::numeric, 1) AS p50_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 1) AS p95_ms
FROM bi.v_agent_step
UNION ALL
SELECT
    'Por ejecución (ms)' AS nivel,
    COUNT(*) AS total,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_latency_ms)::numeric, 1) AS p50_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms)::numeric, 1) AS p95_ms
FROM bi.v_agent_run;
""".strip(),
    },
    {
        "name": "Ejecuciones en modo degradado y fallback",
        "description": "Uso de política por defecto (used_default), ablación y errores por política.",
        "display": "table",
        "size_x": 9,
        "size_y": 5,
        "row": 6,
        "col": 9,
        "sql": """
SELECT
    r.policy_name AS politica,
    r.is_ablation AS es_ablacion,
    COUNT(DISTINCT r.id) AS ejecuciones,
    COUNT(s.id) AS pasos,
    SUM(CASE WHEN s.used_default THEN 1 ELSE 0 END) AS pasos_fallback,
    ROUND(
        100.0 * SUM(CASE WHEN s.used_default THEN 1 ELSE 0 END) / NULLIF(COUNT(s.id), 0),
        2
    ) AS pct_fallback,
    SUM(CASE WHEN s.has_error THEN 1 ELSE 0 END) AS pasos_con_error
FROM bi.v_agent_run r
LEFT JOIN bi.v_agent_step s ON s.run_id = r.id
GROUP BY r.policy_name, r.is_ablation
ORDER BY ejecuciones DESC;
""".strip(),
    },
    {
        "name": "Comparación modelo vs ablación",
        "description": "Tasa de completado, pasos medios y latencia por política y modelo.",
        "display": "table",
        "size_x": 18,
        "size_y": 6,
        "row": 11,
        "col": 0,
        "sql": """
SELECT
    policy_name AS politica,
    COALESCE(model_name, 'sin modelo') AS modelo,
    is_ablation AS es_ablacion,
    COUNT(*) AS total_ejecuciones,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completadas,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS fallidas,
    SUM(CASE WHEN status = 'timed_out' THEN 1 ELSE 0 END) AS expiradas,
    ROUND(
        100.0 * SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    ) AS tasa_completado_pct,
    ROUND(AVG(steps_count)::numeric, 2) AS pasos_medios,
    ROUND(AVG(total_latency_ms)::numeric, 1) AS latencia_media_ms
FROM bi.v_agent_run
GROUP BY policy_name, COALESCE(model_name, 'sin modelo'), is_ablation
ORDER BY is_ablation ASC, total_ejecuciones DESC;
""".strip(),
    },
    {
        "name": "Agente Catalogador — Propuestas de Hojas",
        "description": (
            "Propuestas de hoja del agente catalogador por estado (bi.v_catalog_leaf_proposal) "
            "con la política de su ejecución (bi.v_catalog_agent_summary): número de propuestas, "
            "productos agrupados, medias de productos y señales."
        ),
        "display": "table",
        "size_x": 18,
        "size_y": 6,
        "row": 17,
        "col": 0,
        "sql": """
SELECT
    lp.status AS estado,
    COUNT(*) AS propuestas,
    COALESCE(SUM(lp.product_count), 0) AS productos_agrupados,
    ROUND(AVG(lp.product_count)::numeric, 2) AS productos_medios,
    ROUND(AVG(lp.signal_count)::numeric, 2) AS senales_medias,
    COUNT(DISTINCT lp.run_id) AS ejecuciones,
    STRING_AGG(DISTINCT s.policy_name, ', ') AS politica
FROM bi.v_catalog_leaf_proposal lp
LEFT JOIN bi.v_catalog_agent_summary s ON s.run_id = lp.run_id
GROUP BY lp.status
ORDER BY propuestas DESC;
""".strip(),
    },
]


class MetabaseClient:
    """Minimal Metabase REST API client using urllib.request."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_token: str | None = None

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.session_token:
            headers["X-Metabase-Session"] = self.session_token

        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Metabase API {method} {path} failed ({exc.code}): {detail}") from exc

    def login(self, email: str, password: str) -> None:
        res = self.request("POST", "/api/session", {"username": email, "password": password})
        token = res.get("id") if isinstance(res, dict) else None
        if not token:
            raise RuntimeError("Metabase login succeeded but no session token was returned.")
        self.session_token = token

    def find_database_id(self, db_name: str) -> int:
        res = self.request("GET", "/api/database")
        databases = res.get("data", res) if isinstance(res, dict) else res
        for db in databases:
            if db.get("name") == db_name:
                return int(db["id"])
        available = [db.get("name") for db in databases]
        raise RuntimeError(f"Database {db_name!r} not found in Metabase. Available: {available}")

    def upsert_card(self, db_id: int, spec: dict[str, Any], existing_by_name: dict[str, int]) -> int:
        payload = {
            "name": spec["name"],
            "description": spec["description"],
            "display": spec["display"],
            "dataset_query": {
                "type": "native",
                "native": {"query": spec["sql"]},
                "database": db_id,
            },
            "visualization_settings": {},
        }
        if spec["name"] in existing_by_name:
            card_id = existing_by_name[spec["name"]]
            updated = self.request("PUT", f"/api/card/{card_id}", payload)
            return int(updated["id"])
        created = self.request("POST", "/api/card", payload)
        return int(created["id"])

    def upsert_dashboard(self, card_ids: list[tuple[int, dict[str, Any]]]) -> int:
        dashboards = self.request("GET", "/api/dashboard")
        existing_id: int | None = None
        for dash in dashboards:
            if not dash.get("archived") and dash.get("name") == DASHBOARD_TITLE:
                existing_id = int(dash["id"])
                break

        if existing_id is None:
            created = self.request(
                "POST",
                "/api/dashboard",
                {"name": DASHBOARD_TITLE, "description": DASHBOARD_DESCRIPTION},
            )
            existing_id = int(created["id"])
        else:
            self.request(
                "PUT",
                f"/api/dashboard/{existing_id}",
                {"name": DASHBOARD_TITLE, "description": DASHBOARD_DESCRIPTION},
            )

        dashcards = [
            {
                "id": -(idx + 1),
                "card_id": card_id,
                "row": spec["row"],
                "col": spec["col"],
                "size_x": spec["size_x"],
                "size_y": spec["size_y"],
                "parameter_mappings": [],
                "visualization_settings": {},
            }
            for idx, (card_id, spec) in enumerate(card_ids)
        ]
        self.request("PUT", f"/api/dashboard/{existing_id}", {"dashcards": dashcards})
        return existing_id


def build_dry_run_payload(db_name: str) -> dict[str, Any]:
    return {
        "dashboard": {
            "name": DASHBOARD_TITLE,
            "description": DASHBOARD_DESCRIPTION,
            "database": db_name,
        },
        "cards": [
            {
                "name": c["name"],
                "description": c["description"],
                "display": c["display"],
                "layout": {"row": c["row"], "col": c["col"], "size_x": c["size_x"], "size_y": c["size_y"]},
                "sql": c["sql"],
            }
            for c in CARDS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision ADR 0022 agent dashboard in Metabase.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the dashboard and 6 SQL card definitions without calling Metabase.",
    )
    args = parser.parse_args(argv)

    base_url = os.environ.get("METABASE_URL", "http://127.0.0.1:3000")
    db_name = os.environ.get("METABASE_DB_NAME", "Smart Basket BI")

    if args.dry_run:
        print(json.dumps(build_dry_run_payload(db_name), indent=2, ensure_ascii=False))
        return 0

    email = os.environ.get("METABASE_EMAIL")
    password = os.environ.get("METABASE_PASSWORD")
    if not email or not password:
        print(
            "Error: METABASE_EMAIL and METABASE_PASSWORD must be set (or pass --dry-run).",
            file=sys.stderr,
        )
        return 2

    client = MetabaseClient(base_url)
    client.login(email, password)
    db_id = client.find_database_id(db_name)

    existing_cards_raw = client.request("GET", "/api/card")
    existing_by_name = {
        c["name"]: int(c["id"])
        for c in existing_cards_raw
        if not c.get("archived") and c.get("name")
    }

    card_ids: list[tuple[int, dict[str, Any]]] = []
    for spec in CARDS:
        card_id = client.upsert_card(db_id, spec, existing_by_name)
        card_ids.append((card_id, spec))

    dashboard_id = client.upsert_dashboard(card_ids)
    print(f"Provisioned dashboard {DASHBOARD_TITLE!r} (id={dashboard_id}) with {len(card_ids)} cards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
