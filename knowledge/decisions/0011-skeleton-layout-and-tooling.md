---
type: Architecture Decision
title: "0011 Skeleton layout and tooling"
description: Repository layout, pinned versions, database image, migrations, Compose services and CI of the first implementation delivery.
tags: [decision, architecture, deployment, stack, implementation]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-03T01:10:00+01:00
---
# Context

Decision [0008](/decisions/0008-application-structure-and-stack.md) fixed the stack (Python/FastAPI backend shared by `api` and `worker`, React + Vite + TypeScript PWA behind Caddy, Docker Compose, uv and ruff, latest stable versions pinned) but not the layout, the tools around it or how the database image is built. The first delivery (the skeleton) needed those choices; the author was not available, so they follow `knowledge/` and are recorded here for review.

# Decision

1. **Layout:** `backend/` (uv project, package `smart_basket` under `src/`, tests in `backend/tests/`), `web/` (React app), `infra/` (`db/` image and init script, `caddy/Caddyfile`), `compose.yaml` and `.env.example` at the root, `experiments/` untouched. Backend modules: `api`, `db`, `worker`, `optimizer`, `routing`, `preprocessor`, `llm`.
2. **Versions (2026-11-03), pinned exactly:** Python 3.15.2 (every dependency publishes 3.15 wheels, so the latest Python is used), uv 0.13.6, ruff 0.17.3, FastAPI 0.162.0, SQLAlchemy 2.1.6, Alembic 1.20.1, psycopg 3.3.6, pydantic 2.14.2, APScheduler 3.11.3 (4.x is still a pre-release), httpx 0.28.1, rapidfuzz 3.14.6, pytest 9.2.0; Node 26.13.0 (LTS), React 19.3.1, Vite 8.3.5, TypeScript 7.0.2, vite-plugin-pwa 2.0.0; images `postgres:18.6-trixie`, `caddy:2.11.7-alpine`, `metabase/metabase:v0.65.2.6`, `ghcr.io/valhalla/valhalla-scripted:3.9.1`. Python dependencies are locked in `backend/uv.lock`, web dependencies in `web/package-lock.json`.
3. **Database image:** no official image ships PostGIS and pgvector together, so `infra/db/Dockerfile` adds the PGDG packages (PostGIS 3.7.0, pgvector 0.8.7, versions pinned as build arguments) to the official `postgres:18.6` image. CI builds and migrates the same image.
4. **Database access:** SQLAlchemy 2 (Core and sessions) over psycopg 3. **Migrations** are Alembic revisions with hand-written SQL, shipped inside the package and run by a one-shot `migrate` Compose service (`smart-basket-migrate`) that `api`, `worker` and `metabase` wait for. The schema details are in [0012](/decisions/0012-schema-implementation-details.md).
5. **Roles:** the database owner runs the application and the migrations. `bi_reader` is a login role (password from `.env`) limited to the `bi` schema, read-only; `metabase` owns a separate `metabase` database for Metabase's own content. Both are created by `infra/db/initdb/10-roles.sh` on the first start of the data volume; the migration creates `bi_reader` without login when it does not exist (CI) and grants it only `bi`.
6. **Compose:** services `db`, `migrate`, `api`, `worker`, `routing`, `web` and `metabase`. Only `web` (port 8080 by default) is published on all interfaces; `db`, `routing` and `metabase` are published on `127.0.0.1` for development and Metabase setup. Ollama stays on the host, reached at `OLLAMA_URL` (default `http://host.docker.internal:11434`, mapped with `host-gateway`).
7. **Routing data:** the `routing` service downloads the Geofabrik extract of Castilla y León (`VALHALLA_PBF_URL`, it covers León) on first start and builds the tiles into a volume. Map data is never committed.
8. **Web:** Caddy serves the built app and proxies `/api/*`; the service worker and manifest are served with `no-cache`, hashed assets as immutable. The PWA (vite-plugin-pwa, generated service worker) never caches `/api`.
9. **Worker:** APScheduler `BlockingScheduler` in `Europe/Madrid` with placeholder jobs for ingestion, matching and the BI refresh; the only real job creates the yearly `price_history` partitions ahead of time.
10. **CI (GitHub Actions):** ruff lint and format check, pytest (including the migration tests against the database image, upgrade, downgrade and upgrade again), TypeScript check and web build, and a Compose job that validates `compose.yaml` and builds the backend and web images.

# Consequences

* `docker compose up` starts the whole system from a clean checkout once `.env` exists; the first start of `routing` takes several minutes and needs network access to Geofabrik.
* `.gitattributes` keeps shell scripts with LF line endings: on a Windows checkout with `core.autocrlf`, a CRLF `infra/db/initdb/10-roles.sh` breaks the first start of `db` (no `bi_reader` login, no Metabase database). Found when the stack was first run on the author's laptop.
* Pinned PGDG package versions make the database image reproducible, but PGDG drops superseded packages, so a rebuild can fail until the build arguments are bumped (the Dockerfile says how).
* Moderate npm advisories remain in build-time dependencies of vite-plugin-pwa (workbox-build); they do not reach the served app.

# Revisit when

* APScheduler 4 is released as stable (its API changes).
* A library stops supporting the pinned Python, or the author's laptop cannot run an image.
* The system moves to a VPS ([0008](/decisions/0008-application-structure-and-stack.md)): `SITE_ADDRESS` becomes the domain and the `127.0.0.1` port mappings are dropped.
