"""Persistence of the supermarkets found in OpenStreetMap: `store` rows and `ingest_run` runs.

A store is keyed by `osm_id`, so loading the same Overpass answer twice only updates. A store
that the answer no longer lists is deactivated, never deleted: a missing shop is a fact worth
keeping. Only stores inside the bounding box of the query are deactivated, so a smaller or moved
box never touches the rest of the table. The chain and the zone come from the seed loader; the
import only provides observations.

The run bookkeeping of `ingestion/store.py` is catalog-specific (kind `catalog`, prices), so the
store runs keep their own.
"""

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.config import get_settings
from smart_basket.db import session_scope
from smart_basket.stores.osm import CHAIN_ALIASES, BoundingBox, StoreObservation

log = logging.getLogger("smart_basket.stores")

# Codes of the ten chains of the seed; a store of any other brand never reaches the database.
CHAIN_CODES = frozenset(CHAIN_ALIASES.values())

_UPSERT_STORE = text(
    "insert into store (chain_id, zone_id, osm_id, name, format, address, geom, "
    "opening_hours, is_active) values (:chain, :zone, :osm_id, :name, :format, :address, "
    "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :opening_hours, true) "
    "on conflict (osm_id) do update set chain_id = excluded.chain_id, "
    "zone_id = excluded.zone_id, name = excluded.name, format = excluded.format, "
    "address = excluded.address, geom = excluded.geom, "
    "opening_hours = excluded.opening_hours, is_active = true"
)


class StoreSetupError(RuntimeError):
    """A chain or a zone is missing; the seed loader has to run first."""


@dataclass(frozen=True, slots=True)
class StoreImportSummary:
    """What one import did, for the caller to log and for tests to assert."""

    per_chain: dict[str, int]
    run_ids: tuple[int, ...]
    inserted: int
    updated: int
    deactivated: int


def count_by_chain(observations: Iterable[StoreObservation]) -> dict[str, int]:
    """Stores per chain code, in the order the chains first appear."""
    return {code: len(items) for code, items in _group_by_chain(observations).items()}


def import_stores(
    observations: Iterable[StoreObservation],
    bbox: BoundingBox,
    *,
    mercadona_warehouse: str | None = None,
    now: datetime | None = None,
    database_url: str | None = None,
) -> StoreImportSummary:
    """Upsert the observed stores and deactivate the unseen ones inside `bbox`.

    One `ingest_run` of kind `stores` is recorded per chain that had stores in the answer:
    `ingest_run.chain_id` is required and a single Overpass answer covers every chain of a zone.
    """
    observed = tuple(observations)
    grouped = _group_by_chain(observed)
    if not grouped:
        return StoreImportSummary(per_chain={}, run_ids=(), inserted=0, updated=0, deactivated=0)
    observed_at = now or datetime.now(UTC)
    warehouse = mercadona_warehouse or _default_warehouse()

    with session_scope(database_url) as session:
        chains = dict(session.execute(text("select code, id from chain")).all())
        missing = sorted(set(grouped) - chains.keys())
        if missing:
            raise StoreSetupError(
                f"chain(s) {', '.join(missing)} not found; run `smart-basket-seed` first"
            )
        zones = {code: _zone_for(session, chains[code], code, warehouse) for code in grouped}

    run_ids: list[int] = []
    inserted = updated = 0
    for chain_code, chain_observations in grouped.items():
        run_id, chain_inserted, chain_updated = _import_chain(
            chain_code=chain_code,
            chain_id=chains[chain_code],
            zone_id=zones[chain_code],
            observations=chain_observations,
            observed_at=observed_at,
            database_url=database_url,
        )
        run_ids.append(run_id)
        inserted += chain_inserted
        updated += chain_updated
    deactivated = _deactivate_unseen(observed, bbox=bbox, database_url=database_url)
    return StoreImportSummary(
        per_chain=count_by_chain(observed),
        run_ids=tuple(run_ids),
        inserted=inserted,
        updated=updated,
        deactivated=deactivated,
    )


def log_store_summary(summary: StoreImportSummary) -> None:
    """One log line per import, shared by the CLI and the worker."""
    chains = ", ".join(f"{code}={count}" for code, count in sorted(summary.per_chain.items()))
    log.info(
        "store import: %s stores (%s), %s inserted, %s updated, %s deactivated, runs %s",
        sum(summary.per_chain.values()),
        chains,
        summary.inserted,
        summary.updated,
        summary.deactivated,
        ", ".join(str(run_id) for run_id in summary.run_ids) or "-",
    )


def _group_by_chain(
    observations: Iterable[StoreObservation],
) -> dict[str, tuple[StoreObservation, ...]]:
    grouped: dict[str, list[StoreObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.chain_code, []).append(observation)
    return {code: tuple(items) for code, items in grouped.items()}


def _default_warehouse() -> str:
    codes = get_settings().mercadona_warehouse_codes
    if not codes:
        raise StoreSetupError("MERCADONA_WAREHOUSES is empty; set the León warehouse code")
    return codes[0]


def _zone_for(session: Session, chain_id: int, chain_code: str, warehouse: str) -> int:
    """Mercadona gets its warehouse, a chain with one León zone gets it, the rest the chain one."""
    if chain_code == "mercadona":
        return _require_zone(
            session,
            chain_id=chain_id,
            description=f"warehouse zone '{warehouse}' of chain 'mercadona'",
            kind="warehouse",
            code=warehouse,
        )
    leon_zones = (
        session.execute(
            text("select id from zone where chain_id = :chain and kind <> 'chain' order by id"),
            {"chain": chain_id},
        )
        .scalars()
        .all()
    )
    # The seed gives a chain either no León zone or exactly one; more than one is ambiguous.
    if len(leon_zones) == 1:
        return leon_zones[0]
    return _require_zone(
        session,
        chain_id=chain_id,
        description=f"chain-wide zone 'all' of chain '{chain_code}'",
        kind="chain",
        code="all",
    )


def _require_zone(
    session: Session, *, chain_id: int, description: str, kind: str, code: str
) -> int:
    zone_id = session.execute(
        text("select id from zone where chain_id = :chain and kind = :kind and code = :code"),
        {"chain": chain_id, "kind": kind, "code": code},
    ).scalar_one_or_none()
    if zone_id is None:
        raise StoreSetupError(f"{description} not found; run `smart-basket-seed` first")
    return zone_id


def _import_chain(
    *,
    chain_code: str,
    chain_id: int,
    zone_id: int,
    observations: Sequence[StoreObservation],
    observed_at: datetime,
    database_url: str | None,
) -> tuple[int, int, int]:
    """Open, persist and close the run of one chain, so a failure still leaves a closed row."""
    run_id = _open_run(
        chain_id=chain_id, zone_id=zone_id, started_at=observed_at, database_url=database_url
    )
    try:
        with session_scope(database_url) as session:
            inserted, updated = _upsert_stores(
                session, chain_id=chain_id, zone_id=zone_id, observations=observations
            )
    except BaseException as exc:  # an interrupted persistence must still close the run
        _close_run(
            database_url,
            run_id=run_id,
            status="failed",
            stores_seen=len(observations),
            errors=[{"url": f"osm:{chain_code}", "error": f"persistence failed: {exc}"}],
        )
        raise
    _close_run(
        database_url,
        run_id=run_id,
        status="succeeded",
        stores_seen=len(observations),
        errors=[],
    )
    return run_id, inserted, updated


def _open_run(
    *, chain_id: int, zone_id: int, started_at: datetime, database_url: str | None
) -> int:
    with session_scope(database_url) as session:
        return session.execute(
            text(
                "insert into ingest_run (chain_id, zone_id, kind, started_at, status) "
                "values (:chain, :zone, 'stores', :started, 'running') returning id"
            ),
            {"chain": chain_id, "zone": zone_id, "started": started_at},
        ).scalar_one()


def _close_run(
    database_url: str | None,
    *,
    run_id: int,
    status: str,
    stores_seen: int,
    errors: list[dict[str, str]],
) -> None:
    """Write the final status; `products_seen` holds the stores, the only count the table has."""
    try:
        with session_scope(database_url) as session:
            session.execute(
                text(
                    "update ingest_run set status = :status, "
                    "finished_at = greatest(now(), started_at), "
                    "products_seen = :seen, errors = cast(:errors as jsonb) where id = :run"
                ),
                {
                    "status": status,
                    "seen": stores_seen,
                    "errors": json.dumps(errors, ensure_ascii=False),
                    "run": run_id,
                },
            )
    except Exception:
        log.exception("could not close store run %s", run_id)


def _upsert_stores(
    session: Session,
    *,
    chain_id: int,
    zone_id: int,
    observations: Sequence[StoreObservation],
) -> tuple[int, int]:
    """Insert or update every store by `osm_id`; returns how many of each."""
    osm_ids = [observation.osm_id for observation in observations]
    known = set(
        session.execute(
            text("select osm_id from store where osm_id = any(cast(:osm_ids as text[]))"),
            {"osm_ids": osm_ids},
        ).scalars()
    )
    for observation in observations:
        session.execute(
            _UPSERT_STORE,
            {
                "chain": chain_id,
                "zone": zone_id,
                "osm_id": observation.osm_id,
                "name": observation.name,
                "format": observation.format,
                "address": observation.address,
                "lon": observation.lon,
                "lat": observation.lat,
                "opening_hours": observation.opening_hours,
            },
        )
    inserted = sum(1 for osm_id in osm_ids if osm_id not in known)
    return inserted, len(osm_ids) - inserted


def _deactivate_unseen(
    observations: Sequence[StoreObservation],
    *,
    bbox: BoundingBox,
    database_url: str | None,
) -> int:
    """Deactivate the stores of the ten chains inside `bbox` that the answer no longer lists.

    Only stores inside the box are considered: a smaller or moved box says nothing about the
    stores outside it. An answer without stores would deactivate the whole box, so it is never
    trusted: the caller returns before reaching this function in that case.
    """
    seen = sorted({observation.osm_id for observation in observations})
    with session_scope(database_url) as session:
        result = session.execute(
            text(
                "update store set is_active = false where is_active and chain_id in ("
                "select id from chain where code = any(cast(:codes as text[]))) "
                "and not (osm_id = any(cast(:seen as text[]))) "
                "and ST_Covers("
                "ST_MakeEnvelope(:west, :south, :east, :north, 4326)::geography, geom)"
            ),
            {
                "codes": sorted(CHAIN_CODES),
                "seen": seen,
                "west": bbox.west,
                "south": bbox.south,
                "east": bbox.east,
                "north": bbox.north,
            },
        )
        return result.rowcount
