#!/usr/bin/env bash
# Backend checks as in CI (ruff lint, ruff format, pytest) inside the Python 3.15 image, so they
# run on any machine with Docker, Windows included, without installing Python 3.15.
#
#   bash scripts/test-backend.sh [--db] [pytest arguments...]
#
# --db joins the Compose network and also runs the database tests. They use TEST_DATABASE_URL
# or, by default, the database TEST_DB_NAME (smart_basket_test) of the running `db` service with
# the password from the main checkout's .env (worktrees share it). Start it with
# `docker compose up -d db`; give parallel runs different TEST_DB_NAME values, since the
# migration tests drop and recreate the schema.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
main="$(dirname "$(git -C "$root" rev-parse --path-format=absolute --git-common-dir)")"
mount="$root"
command -v cygpath >/dev/null && mount="$(cygpath -w "$root")"

opts=(--rm -v "$mount:/repo:ro" -v smart-basket-uv-cache:/uv-cache
  -e UV_PROJECT_ENVIRONMENT=/tmp/venv -e UV_LINK_MODE=copy -e UV_PYTHON_DOWNLOADS=never
  -e UV_CACHE_DIR=/uv-cache -w /repo/backend)

if [ "${1:-}" = "--db" ]; then
  shift
  url="${TEST_DATABASE_URL:-}"
  if [ -z "$url" ]; then
    password="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$main/.env" 2>/dev/null | tr -d '\r')"
    user="$(sed -n 's/^POSTGRES_USER=//p' "$main/.env" 2>/dev/null | tr -d '\r')"
    [ -n "$password" ] || { echo "POSTGRES_PASSWORD not found in $main/.env" >&2; exit 2; }
    url="postgresql+psycopg://${user:-smart_basket}:${password}@db:5432/${TEST_DB_NAME:-smart_basket_test}"
  fi
  opts+=(--network smart-basket_default -e "TEST_DATABASE_URL=$url")
fi

# Git Bash would rewrite the container paths (/repo...) into Windows paths.
MSYS_NO_PATHCONV=1 docker run "${opts[@]}" python:3.15.2-slim-trixie sh -c '
  pip install -q --root-user-action=ignore uv==0.13.6 2>/dev/null
  uv sync -q --frozen &&
  uv run --frozen ruff check --no-cache . &&
  uv run --frozen ruff format --no-cache --check . &&
  uv run --frozen pytest -q -p no:cacheprovider "$@"
' sh "$@"
