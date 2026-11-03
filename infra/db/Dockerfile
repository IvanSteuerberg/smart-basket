# PostgreSQL 18 with PostGIS and pgvector (decisions 0003, 0007). No official image ships both,
# so the extensions come from the PGDG packages of the official image's own repository.
# Bump the versions together: `apt-cache policy postgresql-18-postgis-3 postgresql-18-pgvector`.
FROM postgres:18.6-trixie

ARG POSTGIS_VERSION=3.7.0+dfsg-1.pgdg13+1
ARG PGVECTOR_VERSION=0.8.7-1.pgdg13+1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      "postgresql-18-postgis-3=${POSTGIS_VERSION}" \
      "postgresql-18-postgis-3-scripts=${POSTGIS_VERSION}" \
      "postgresql-18-pgvector=${PGVECTOR_VERSION}" \
 && rm -rf /var/lib/apt/lists/*

COPY initdb/ /docker-entrypoint-initdb.d/
