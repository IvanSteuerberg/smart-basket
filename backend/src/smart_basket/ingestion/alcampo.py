"""Alcampo adapter: public server-rendered catalog via RadarSuper (decision 0006, NFR-07).

Direct automated access to `compraonline.alcampo.es` hits an AWS WAF `405` interactive CAPTCHA
whose token re-challenged after 1 hour in T2 (`experiments/supervised-unlock/results.jsonl`),
exceeding the `<= 1 puzzle/week` pass criterion of NFR-13. RadarSuper (`radarsuper.com/alcampo`)
publishes Alcampo Spain's daily-updated online catalog across 152 leaf categories as plain
server-rendered HTML, explicitly allowed by its `robots.txt` (`Allow: /`).
"""

from __future__ import annotations

from smart_basket.ingestion.carrefour import RadarSuperAdapter


class AlcampoAdapter(RadarSuperAdapter):
    """Plain-HTTP adapter for Alcampo Spain via RadarSuper's public category pages."""

    chain_code = "alcampo"
    chain_slug = "alcampo"
    zone_kind = "postal_code"
    default_zone = "24003"
