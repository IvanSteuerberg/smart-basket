"""Contract tests for the Alcampo RadarSuper plain-HTTP adapter."""

from __future__ import annotations

from decimal import Decimal

import httpx

from smart_basket.ingestion.alcampo import AlcampoAdapter
from smart_basket.ingestion.base import CategoryObservation, ProductObservation

INDEX_HTML = """
<html><body>
  <a href="/alcampo/c/aceite-especias-salsas-12">Aceite, especias y salsas</a>
  <a href="/alcampo/c/aceite-vinagre-sal-112">Aceite, vinagre y sal</a>
</body></html>
"""

CAT_HTML = (
    "<html><body><h1>Aceite, vinagre y sal en Alcampo</h1>"
    r'<script>self.__next_f.push([1,"{\"item\":{'
    r"\"key\":\"/alcampo/p/aceite-oliva-virgen-extra-1-l-alcampo\","
    r"\"name\":\"Aceite de oliva virgen extra 1 l.\","
    r"\"brand\":\"Alcampo\",\"price\":7.95,\"unit\":\"L\",\"size\":1,"
    r"\"chain\":\"Alcampo\",\"image\":\"/img/p/aove-alcampo.jpg\","
    r'\"url\":\"/alcampo/p/aceite-oliva-virgen-extra-1-l-alcampo\"}}"])</script>'
    "</body></html>"
)


def test_alcampo_adapter_crawls_radarsuper_categories():
    routes = {
        "https://radarsuper.com/alcampo": INDEX_HTML,
        "https://radarsuper.com/alcampo/c/aceite-vinagre-sal-112": CAT_HTML,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(str(request.url))
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AlcampoAdapter(delay=0.0, client=client)
    observations = list(adapter.crawl("24003"))

    cats = [o for o in observations if isinstance(o, CategoryObservation)]
    prods = [o for o in observations if isinstance(o, ProductObservation)]

    assert len(cats) == 1
    assert cats[0].name == "Aceite, vinagre y sal"
    assert len(prods) == 1
    assert prods[0].sku == "aceite-oliva-virgen-extra-1-l-alcampo"
    assert prods[0].price == Decimal("7.95")
    assert prods[0].base_unit == "l"
    assert prods[0].price_per_unit == Decimal("7.9500")
