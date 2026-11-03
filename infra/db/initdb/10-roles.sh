#!/usr/bin/env bash
# Runs once, when the data volume is initialized. Creates:
#  * bi_reader: login role for Metabase, read-only on the `bi` schema (grants come from the
#    Alembic migrations, which create it without login if this script did not run).
#  * metabase: owner of Metabase's own application database (questions, dashboards, users).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v bi_password="${BI_READER_PASSWORD:?BI_READER_PASSWORD is required}" \
  -v mb_password="${METABASE_DB_PASSWORD:?METABASE_DB_PASSWORD is required}" <<'SQL'
create role bi_reader login password :'bi_password';
create role metabase login password :'mb_password';
create database metabase owner metabase;
SQL
