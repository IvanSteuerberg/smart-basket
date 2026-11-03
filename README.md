# Smart Basket

Business Intelligence and semantic recommendation engine for grocery shopping: given a shopping list, it proposes the combination of products and supermarkets that minimizes total cost and travel time, including equivalences between national brands and private labels.

> **Status:** implementation phase (since 2026-11-03). The skeleton runs with Docker Compose; see the implementation status in the [system overview](knowledge/architecture/system-overview.md#implementation-status).

## Problem

Prices change constantly and the retail market is fragmented across chains. Comparing prices and finding cheaper equivalent alternatives by hand is not feasible day to day.

## Proposal

A recommender agent that, from a generic or specific shopping list:

- finds **functionally equivalent** products across brands and chains,
- computes the **lowest-cost** basket,
- takes **travel time** between stores into account.

## Architecture

| Module | Responsibility |
| --- | --- |
| Ingestion (scraping) | Periodic extraction and refresh of catalogs and prices from each chain. |
| Persistence | Price history, user data and vector representations of the catalog. |
| Recommender | Semantic product matching and shopping-route optimization. |
| Interface | Web and mobile app: shopping lists, savings history and routes. |

Architecture decisions (single PostgreSQL database, routing in three layers, agent as orchestrator, stack and layout) are recorded in the [knowledge base](knowledge/index.md).

## Repository layout

```
backend/              Python package smart_basket (uv project): API, worker, migrations, recommender
  src/smart_basket/
    api/              FastAPI app (/api/health, OpenAPI at /api/docs)
    db/               Engine, sessions and Alembic migrations (hand-written SQL)
    worker/           APScheduler process (ingestion, matching and BI refresh placeholders)
  tests/              pytest suite (synthetic data only)
web/                  React + Vite + TypeScript PWA (Spanish UI)
infra/
  db/                 PostgreSQL 18 image with PostGIS and pgvector, first-start role script
  caddy/              Caddyfile: serves the web app and proxies /api to the backend
compose.yaml          db, migrate, api, worker, routing (Valhalla), web (Caddy), metabase
.env.example          Configuration template (copy to .env, which is git-ignored)
experiments/          One-off benchmarks (LLM benchmark of decision 0005)
knowledge/            Engineering knowledge base (OKF v0.2): vision, architecture, decisions
docs/
  idea-base/          Concept document (LaTeX, Spanish)
  memoria-prompts/    Generative AI prompt log (LaTeX, Spanish)
    entradas/         One entry file per month, included from memoria-prompts.tex
    fuentes/          Raw answers from the second AI source
  registro-actividad/ Weekly activity log of all course work (LaTeX, Spanish)
scripts/
  osf_publish.py      Compile the documents and publish the PDFs to OSF (dry run by default)
  osf_index.py        Generate the OSF wiki index from the live file listing (+ osf_index.json)
```

## Recommender components

* **Basket optimizer** (`backend/src/smart_basket/optimizer/`): pure Python, no database or network. `optimize(BasketRequest)` takes interpreted lines, candidate stores with products, prices and promotions, a travel-time matrix, max stores and lambda, and returns per-store purchases, totals, minutes, visiting order, missing lines and the engine version. Rules: decisions 0010 and 0013.
* **Routing** (`backend/src/smart_basket/routing/`): `RoutingEngine` protocol (origin and stores in, minutes matrix out) and a Valhalla client.
* **Rule-based preprocessor** (`backend/src/smart_basket/preprocessor/`): `Preprocessor(lexicon).preprocess(text)` turns a free-text list into items with the LLM item schema and marks the lines the LLM must interpret. The lexicon sits behind an interface; tests use the synthetic `backend/tests/fixtures/lexicon_es.json`. Rules: decision 0014.
* **LLM providers** (`backend/src/smart_basket/llm/`): Ollama and Gemini behind one protocol; `interpret_unresolved` sends only the unresolved lines and falls back to the rules (FR-41).

The evaluation on the benchmark lists prints its figures with `uv run pytest tests/preprocessor -s -k benchmark`.

## Running with Docker Compose

Requires Docker with Compose v2. Ollama runs natively on the host (decision 0005), outside Compose.

```bash
cp .env.example .env
```

Edit `.env` and set the three passwords, then:

```bash
docker compose up -d --build
```

* Web app: <http://localhost:8080> (the placeholder page calls `/api/health`).
* API: <http://localhost:8080/api/health>, OpenAPI docs at <http://localhost:8080/api/docs>.
* Metabase: <http://localhost:3000>. On first use, add a PostgreSQL database with host `db`, database `smart_basket`, user `bi_reader` and the `BI_READER_PASSWORD` of `.env`; that role only sees the `bi` schema.
* Valhalla: <http://localhost:8002/status>. On first start it downloads the Castilla y León extract from Geofabrik and builds the routing tiles (several minutes); later starts reuse the `routing-data` volume.
* PostgreSQL: `127.0.0.1:5432` (user and password from `.env`).

The `migrate` service applies the migrations and exits; `api`, `worker` and `metabase` wait for it. The roles `bi_reader` and `metabase` are created when the data volume is first initialized, so changing their passwords later needs `ALTER ROLE` (or `docker compose down -v`, which deletes all data).

Ollama: install it on the host, pull the model in `OLLAMA_MODEL` (`ollama pull qwen3.5:0.8b`) and keep `ollama serve` running. The containers reach it at `OLLAMA_URL`. `LLM_PROVIDER=none` runs in rules-only mode (FR-41).

## Developing

Backend (needs [uv](https://docs.astral.sh/uv/); it installs Python 3.15 itself):

```bash
cd backend && uv sync
```

```bash
docker compose up -d db && uv run smart-basket-migrate upgrade head
```

```bash
uv run smart-basket-api
```

The backend reads `DATABASE_URL` and the other settings from the environment or a `.env` file in the working directory (see `smart_basket/config.py`). Lint and format with ruff:

```bash
uv run ruff check . && uv run ruff format --check .
```

Web (Node 26), with `/api` proxied to `http://localhost:8000` (override with `VITE_API_PROXY`):

```bash
cd web && npm ci && npm run dev
```

## Testing

```bash
cd backend && uv run pytest
```

The migration tests need a disposable database; they downgrade it to empty and upgrade it again:

```bash
docker compose exec db createdb -U smart_basket smart_basket_test
```

```bash
TEST_DATABASE_URL=postgresql+psycopg://smart_basket:<password>@localhost:5432/smart_basket_test uv run pytest tests/db
```

Web type check and build:

```bash
cd web && npm run typecheck && npm run build
```

CI (`.github/workflows/ci.yml`) runs ruff, pytest with the migration tests against the repository's database image, the TypeScript check and web build, and validates and builds the Compose images.

## Building the documentation

Requires a LaTeX distribution (TeX Live or MiKTeX). Build from each document's folder, since `\input` paths are relative:

```bash
cd docs/memoria-prompts && latexmk -pdf memoria-prompts.tex
```

## Context

Course project for *Sistemas de Información de Gestión y Business Intelligence* (Management Information Systems and Business Intelligence), Computer Engineering degree, Universidad de León, 2026-2027.

Author: Iván Rodríguez Steuerberg.
