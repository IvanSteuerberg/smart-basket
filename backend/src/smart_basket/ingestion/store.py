"""Persistence shared by every chain adapter: runs, products and change-only prices (0006, 0007).

The chain and the zone come from the seed loader; the adapter only provides observations. The
price stays in `price_current` until the next run sees another value, and only then is the old
interval closed in `price_history`.

The run is bookkept across three transactions (open, persist, close) so a failure while
persisting still leaves an `ingest_run` row with a final status.
"""

import gzip
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.db import session_scope
from smart_basket.ingestion.base import (
    CategoryObservation,
    ChainAdapter,
    CrawlResult,
    FinalStatus,
    ProductObservation,
    RawResponse,
    RunStatus,
    collect,
)

log = logging.getLogger("smart_basket.ingestion")

# A complete run that sees less than half of the available catalog is not trusted to close
# price intervals: the missing products were most likely a broken crawl, not a withdrawal.
MIN_SEEN_SHARE = 0.5

# A `running` row this old belongs to a process that died and will never close it.
ABANDONED_RUN_AFTER = timedelta(hours=6)

# Option B of decision 0006: a flyer staple not seen for this long stops being retained.
STAPLE_RETENTION_TTL = timedelta(days=21)

# Private-label staples of the flyer chains (Lidl's own brands and a few shared names): only
# these are worth retaining once their flyer is gone, because the regular price is what the
# product will cost in every future flyer.
STAPLE_PRIVATE_LABEL_BRANDS = frozenset(
    {
        "milbona",
        "bellarom",
        "baresa",
        "alesto",
        "chef select",
        "kania",
        "combino",
        "formil",
        "cien",
        "w5",
        "solevita",
        "freeway",
        "crownfield",
        "campo largo",
        "nixe",
        "pikok",
        "gelatelli",
        "sondey",
        "trattoria alfredo",
        "marca guia",
        "marca guía",
        "eco+",
    }
)


def is_retendable_staple_name(name: str) -> bool:
    """Whether a flyer product is a private-label staple worth retaining (Option B, 0006).

    Seasonal and limited-edition items (`deluxe`, `artículo limitado`) are excluded: they never
    come back at their flyer price, so retaining them would freeze a stale offer forever.
    """
    low = name.casefold()
    if "deluxe" in low or "artículo limitado" in low or "articulo limitado" in low:
        return False
    return any(brand in low for brand in STAPLE_PRIVATE_LABEL_BRANDS)


class IngestSetupError(RuntimeError):
    """The chain or the zone is missing; the seed loader has to run first."""


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """What one catalog run did, for the caller to log and for tests to assert."""

    chain_code: str
    zone_code: str
    run_id: int
    status: FinalStatus
    complete: bool
    products_seen: int
    prices_changed: int
    errors: tuple[dict[str, str], ...]


def ingest_catalog(
    adapter: ChainAdapter,
    zone_code: str,
    *,
    data_dir: Path,
    max_categories: int | None = None,
    now: datetime | None = None,
    database_url: str | None = None,
) -> IngestSummary:
    """Crawl one zone with `adapter` and persist the result, closing the `ingest_run`."""
    zone_kind = getattr(adapter, "zone_kind", "warehouse")
    retention_policy = getattr(adapter, "retention_policy", "live_sync")
    started_at = datetime.now(UTC)
    with session_scope(database_url) as session:
        chain_id = _lookup_chain(session, adapter.chain_code)
        zone_id = _lookup_zone(session, chain_id, adapter.chain_code, zone_code, zone_kind)
        run_id = _open_run(session, chain_id=chain_id, zone_id=zone_id, started_at=started_at)

    try:
        result = collect(adapter, zone_code, max_categories=max_categories)
    except BaseException as exc:  # an interrupted crawl must still close the run
        _close_failed_run(
            database_url,
            run_id=run_id,
            products_seen=0,
            errors=[{"url": zone_code, "error": str(exc)}],
        )
        raise

    # The observation is the end of the crawl: what the catalog said when it finished.
    observation_time = now or datetime.now(UTC)
    try:
        with session_scope(database_url) as session:
            prices_changed, errors, status = _persist(
                session,
                run_id=run_id,
                chain_id=chain_id,
                zone_id=zone_id,
                chain_code=adapter.chain_code,
                zone_code=zone_code,
                result=result,
                data_dir=data_dir,
                observation_time=observation_time,
                retention_policy=retention_policy,
            )
    except BaseException as exc:  # an interrupted persistence must still close the run
        _close_failed_run(
            database_url,
            run_id=run_id,
            products_seen=len(result.products),
            errors=[{"url": zone_code, "error": f"persistence failed: {exc}"}],
        )
        raise

    _close_run(
        database_url,
        run_id=run_id,
        status=status,
        products_seen=len(result.products),
        prices_changed=prices_changed,
        errors=errors,
    )
    return IngestSummary(
        chain_code=adapter.chain_code,
        zone_code=zone_code,
        run_id=run_id,
        status=status,
        complete=result.complete and status == "succeeded",
        products_seen=len(result.products),
        prices_changed=prices_changed,
        errors=tuple(errors),
    )


def _close_failed_run(
    database_url: str | None,
    *,
    run_id: int,
    products_seen: int,
    errors: list[dict[str, str]],
) -> None:
    """Close a run as failed after an error without masking that original error."""
    try:
        _close_run(
            database_url,
            run_id=run_id,
            status="failed",
            products_seen=products_seen,
            prices_changed=0,
            errors=errors,
        )
    except Exception:
        log.exception("could not close run %s after a failure", run_id)


def log_ingest_summary(summary: IngestSummary) -> None:
    """One log line per run, shared by the CLI and the worker."""
    log.info(
        "catalog run %s for %s/%s: %s, %s products, %s price changes, %s errors",
        summary.run_id,
        summary.chain_code,
        summary.zone_code,
        summary.status,
        summary.products_seen,
        summary.prices_changed,
        len(summary.errors),
    )


def _lookup_chain(session: Session, chain_code: str) -> int:
    chain_id = session.execute(
        text("select id from chain where code = :code"), {"code": chain_code}
    ).scalar_one_or_none()
    if chain_id is None:
        raise IngestSetupError(f"chain '{chain_code}' not found; run `smart-basket-seed` first")
    return chain_id


def _lookup_zone(
    session: Session, chain_id: int, chain_code: str, zone_code: str, zone_kind: str
) -> int:
    zone_id = session.execute(
        text("select id from zone where chain_id = :chain and kind = :kind and code = :code"),
        {"chain": chain_id, "kind": zone_kind, "code": zone_code},
    ).scalar_one_or_none()
    if zone_id is None:
        raise IngestSetupError(
            f"{zone_kind} zone '{zone_code}' of chain '{chain_code}' not found; "
            "run `smart-basket-seed` first"
        )
    return zone_id


def _open_run(session: Session, *, chain_id: int, zone_id: int, started_at: datetime) -> int:
    """Mark abandoned runs failed, then insert the `running` row with its own transaction."""
    _close_abandoned_runs(session, chain_id=chain_id, zone_id=zone_id)
    return session.execute(
        text(
            "insert into ingest_run (chain_id, zone_id, kind, started_at, status) "
            "values (:chain, :zone, 'catalog', :started, 'running') returning id"
        ),
        {"chain": chain_id, "zone": zone_id, "started": started_at},
    ).scalar_one()


def _close_abandoned_runs(session: Session, *, chain_id: int, zone_id: int) -> None:
    """A run of the same chain and zone still `running` after six hours will never close itself."""
    session.execute(
        text(
            "update ingest_run set status = 'failed', "
            "finished_at = greatest(now(), started_at), "
            "errors = cast(:errors as jsonb) "
            "where chain_id = :chain and zone_id = :zone and status = 'running' "
            "and started_at < now() - :age"
        ),
        {
            "chain": chain_id,
            "zone": zone_id,
            "age": ABANDONED_RUN_AFTER,
            "errors": json.dumps([{"url": None, "error": "abandoned run"}]),
        },
    )


def _close_run(
    database_url: str | None,
    *,
    run_id: int,
    status: RunStatus,
    products_seen: int,
    prices_changed: int,
    errors: list[dict[str, str]],
) -> None:
    """Write the final status and commit it, whatever happened before."""
    with session_scope(database_url) as session:
        session.execute(
            text(
                "update ingest_run set status = :status, "
                "finished_at = greatest(now(), started_at), "
                "products_seen = :seen, prices_changed = :changed, "
                "errors = cast(:errors as jsonb) where id = :run"
            ),
            {
                "status": status,
                "seen": products_seen,
                "changed": prices_changed,
                "errors": json.dumps(errors, ensure_ascii=False),
                "run": run_id,
            },
        )


def _persist(
    session: Session,
    *,
    run_id: int,
    chain_id: int,
    zone_id: int,
    chain_code: str,
    zone_code: str,
    result: CrawlResult,
    data_dir: Path,
    observation_time: datetime,
    retention_policy: str = "live_sync",
) -> tuple[int, list[dict[str, str]], FinalStatus]:
    """Write the crawl in one transaction: prices changed, errors and the final status."""
    _lock_zone(session, zone_id)

    _upsert_categories(session, chain_id, result.categories)
    category_ids = dict(
        session.execute(
            text("select code, id from chain_category where chain_id = :chain"),
            {"chain": chain_id},
        ).all()
    )
    prices_changed = 0
    for product in result.products:
        product_id = _upsert_product(
            session,
            chain_id=chain_id,
            zone_id=zone_id,
            product=product,
            category_id=category_ids.get(product.category_code),
            observation_time=observation_time,
        )
        prices_changed += _update_price(
            session,
            product_id=product_id,
            zone_id=zone_id,
            product=product,
            run_id=run_id,
            observation_time=observation_time,
        )
        if retention_policy == "controlled_staples":
            if (
                product.regular_price is not None
                and product.regular_price > product.price
                and not product.is_temporary
                and is_retendable_staple_name(product.name)
            ):
                _record_flyer_reference_promotion(
                    session,
                    chain_id=chain_id,
                    zone_id=zone_id,
                    product_id=product_id,
                    product=product,
                    run_id=run_id,
                    observation_time=observation_time,
                )
            elif product.is_temporary or product.regular_price is None:
                # The product no longer travels with a regular price (or is temporary), so an
                # older flyer reference must not be used to revert its price later on.
                _delete_flyer_promotions(session, chain_id=chain_id, product_id=product_id)

    for raw in result.raw:
        _store_raw_response(
            session,
            run_id=run_id,
            chain_code=chain_code,
            raw=raw,
            data_dir=data_dir,
            observation_time=observation_time,
        )

    errors = [{"url": error.url, "error": error.error} for error in result.errors]
    status = result.status
    if result.complete or (result.status == "succeeded" and not result.products):
        available = _available_count(session, chain_id=chain_id, zone_id=zone_id)
        if result.complete and retention_policy == "controlled_staples":
            # Weekly flyers rotate their products by design, so the seen-share cutoff does not
            # apply: unseen staples keep selling at their recorded reference price while the
            # 21-day TTL holds, and everything else is marked unavailable (Option B, 0006).
            prices_changed += _apply_controlled_staple_retention(
                session,
                chain_id=chain_id,
                zone_id=zone_id,
                run_id=run_id,
                observation_time=observation_time,
            )
        elif result.complete and len(result.products) >= available * MIN_SEEN_SHARE:
            _mark_unavailable(
                session, chain_id=chain_id, zone_id=zone_id, observation_time=observation_time
            )
        elif available:
            errors.append(
                {
                    "url": zone_code,
                    "error": (
                        f"only {len(result.products)} of {available} available products seen; "
                        "kept every product as available"
                    ),
                }
            )
            status = "partial"
    return prices_changed, errors, status


def _lock_zone(session: Session, zone_id: int) -> None:
    """Serialize persistence per zone so two runs cannot close the same interval at once."""
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"smart_basket.ingest:{zone_id}"},
    )


def _available_count(session: Session, *, chain_id: int, zone_id: int) -> int:
    return session.execute(
        text(
            "select count(*) from chain_product_zone z "
            "join chain_product p on p.id = z.chain_product_id "
            "where p.chain_id = :chain and z.zone_id = :zone and z.is_available"
        ),
        {"chain": chain_id, "zone": zone_id},
    ).scalar_one()


def _upsert_categories(
    session: Session, chain_id: int, categories: tuple[CategoryObservation, ...]
) -> None:
    for category in categories:
        session.execute(
            text(
                "insert into chain_category (chain_id, code, name, parent_code) "
                "values (:chain, :code, :name, :parent) "
                "on conflict (chain_id, code) do update "
                "set name = excluded.name, parent_code = excluded.parent_code"
            ),
            {
                "chain": chain_id,
                "code": category.code,
                "name": category.name,
                "parent": category.parent_code,
            },
        )


def _upsert_product(
    session: Session,
    *,
    chain_id: int,
    zone_id: int,
    product: ProductObservation,
    category_id: int | None,
    observation_time: datetime,
) -> int:
    product_id = session.execute(
        text(
            "insert into chain_product (chain_id, chain_sku, name, packaging, url, image_url, "
            "base_quantity, base_unit, pack_count, chain_category_id, first_seen, last_seen, "
            "is_active) values (:chain, :sku, :name, :packaging, :url, :image_url, :quantity, "
            ":unit, :pack_count, :category, :now, :now, true) "
            "on conflict (chain_id, chain_sku) do update set name = excluded.name, "
            "packaging = excluded.packaging, url = excluded.url, "
            "image_url = excluded.image_url, "
            "base_quantity = excluded.base_quantity, base_unit = excluded.base_unit, "
            "pack_count = excluded.pack_count, chain_category_id = excluded.chain_category_id, "
            "last_seen = excluded.last_seen, is_active = true "
            "returning id"
        ),
        {
            "chain": chain_id,
            "sku": product.sku,
            "name": product.name,
            "packaging": product.packaging,
            "url": product.url,
            "image_url": product.image_url,
            "quantity": product.base_quantity,
            "unit": product.base_unit,
            "pack_count": product.pack_count,
            "category": category_id,
            "now": observation_time,
        },
    ).scalar_one()
    session.execute(
        text(
            "insert into chain_product_zone "
            "(chain_product_id, zone_id, first_seen, last_seen, is_available) "
            "values (:product, :zone, :now, :now, true) "
            "on conflict (chain_product_id, zone_id) do update "
            "set last_seen = excluded.last_seen, is_available = true"
        ),
        {"product": product_id, "zone": zone_id, "now": observation_time},
    )
    return product_id


def _update_price(
    session: Session,
    *,
    product_id: int,
    zone_id: int,
    product: ProductObservation,
    run_id: int,
    observation_time: datetime,
) -> int:
    """Keep `price_current` current and close the old interval only when something changed."""
    current = session.execute(
        text(
            "select price, price_per_unit, valid_from from price_current "
            "where chain_product_id = :product and zone_id = :zone"
        ),
        {"product": product_id, "zone": zone_id},
    ).one_or_none()
    if current is None:
        session.execute(
            text(
                "insert into price_current (chain_product_id, zone_id, price, price_per_unit, "
                "valid_from, last_seen_run, last_seen_at) "
                "values (:product, :zone, :price, :unit_price, :now, :run, :now)"
            ),
            {
                "product": product_id,
                "zone": zone_id,
                "price": product.price,
                "unit_price": product.price_per_unit,
                "now": observation_time,
                "run": run_id,
            },
        )
        return 1

    old_price, old_unit_price, old_from = current
    if old_price == product.price and old_unit_price == product.price_per_unit:
        session.execute(
            text(
                "update price_current set last_seen_run = :run, last_seen_at = :now "
                "where chain_product_id = :product and zone_id = :zone"
            ),
            {"run": run_id, "now": observation_time, "product": product_id, "zone": zone_id},
        )
        return 0

    if observation_time <= old_from:
        # An observation that is not newer than the current interval cannot replace it: closing
        # the interval would make valid_to <= valid_from, and an older price would travel back in
        # time. Only the sighting is refreshed.
        session.execute(
            text(
                "update price_current set last_seen_run = :run, last_seen_at = :now "
                "where chain_product_id = :product and zone_id = :zone"
            ),
            {"run": run_id, "now": observation_time, "product": product_id, "zone": zone_id},
        )
        return 0

    session.execute(
        text(
            "insert into price_history (chain_product_id, zone_id, price, price_per_unit, "
            "valid_from, valid_to, run_id) "
            "values (:product, :zone, :price, :unit_price, :valid_from, :now, :run)"
        ),
        {
            "product": product_id,
            "zone": zone_id,
            "price": old_price,
            "unit_price": old_unit_price,
            "valid_from": old_from,
            "now": observation_time,
            "run": run_id,
        },
    )
    session.execute(
        text(
            "update price_current set price = :price, price_per_unit = :unit_price, "
            "valid_from = :now, last_seen_run = :run, last_seen_at = :now "
            "where chain_product_id = :product and zone_id = :zone"
        ),
        {
            "product": product_id,
            "zone": zone_id,
            "price": product.price,
            "unit_price": product.price_per_unit,
            "now": observation_time,
            "run": run_id,
        },
    )
    return 1


def _store_raw_response(
    session: Session,
    *,
    run_id: int,
    chain_code: str,
    raw: RawResponse,
    data_dir: Path,
    observation_time: datetime,
) -> None:
    digest = hashlib.sha256(raw.body).hexdigest()
    relative = Path("raw") / chain_code / observation_time.strftime("%Y-%m-%d")
    relative = relative / f"{digest}.json.gz"
    target = data_dir / relative
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wb") as body:
            body.write(raw.body)
    session.execute(
        text(
            "insert into raw_response (run_id, url, fetched_at, status_code, sha256, path) "
            "values (:run, :url, :fetched_at, :status, :sha, :path)"
        ),
        {
            "run": run_id,
            "url": raw.url,
            "fetched_at": observation_time,
            "status": raw.status_code,
            "sha": digest,
            "path": relative.as_posix(),
        },
    )


def _mark_unavailable(
    session: Session, *, chain_id: int, zone_id: int, observation_time: datetime
) -> None:
    """After a trusted complete run: mark unseen products unavailable and deactivate them.

    Seen products were just stamped with `observation_time`, so anything older was not seen.
    """
    session.execute(
        text(
            "update chain_product_zone z set is_available = false "
            "from chain_product p "
            "where p.id = z.chain_product_id and p.chain_id = :chain "
            "and z.zone_id = :zone and z.is_available and z.last_seen < :observed"
        ),
        {"chain": chain_id, "zone": zone_id, "observed": observation_time},
    )
    session.execute(
        text(
            "update chain_product p set is_active = false "
            "where p.chain_id = :chain and p.is_active and not exists ("
            "select 1 from chain_product_zone z "
            "where z.chain_product_id = p.id and z.is_available)"
        ),
        {"chain": chain_id},
    )


def _flyer_date(value: str | None) -> date | None:
    """Parse a flyer date like `2026-11-16` (ISO or ISO datetime prefix); None when invalid."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _record_flyer_reference_promotion(
    session: Session,
    *,
    chain_id: int,
    zone_id: int,
    product_id: int,
    product: ProductObservation,
    run_id: int,
    observation_time: datetime,
) -> None:
    """Store the flyer offer with its regular price, so a later run can revert to it.

    The promotion is `applied_in_price` (the offer price is the observed price) and carries
    the pre-offer `reference_price` that the retention reads back when the flyer rotates.
    """
    v_from = _flyer_date(product.valid_from) or observation_time.date()
    v_until = _flyer_date(product.valid_until)
    if v_until is None or v_until < v_from:
        v_until = v_from + timedelta(days=7)
    promotion_id = session.execute(
        text(
            "insert into promotion (chain_id, kind, promo_price, reference_price, "
            "applied_in_price, valid, source, source_ref, run_id) "
            "values (:chain, 'promo_price', :promo_price, :reference_price, true, "
            "daterange(:v_from, :v_until, '[]'), 'flyer', :source_ref, :run) returning id"
        ),
        {
            "chain": chain_id,
            "promo_price": product.price,
            "reference_price": product.regular_price,
            "v_from": v_from,
            "v_until": v_until,
            "source_ref": product.sku,
            "run": run_id,
        },
    ).scalar_one()
    session.execute(
        text(
            "insert into promotion_target (promotion_id, chain_product_id) "
            "values (:promotion, :product)"
        ),
        {"promotion": promotion_id, "product": product_id},
    )
    session.execute(
        text("insert into promotion_zone (promotion_id, zone_id) values (:promotion, :zone)"),
        {"promotion": promotion_id, "zone": zone_id},
    )


def _delete_flyer_promotions(session: Session, *, chain_id: int, product_id: int) -> None:
    """Drop the flyer promotions of one product, targets and zones cascading along."""
    session.execute(
        text(
            "delete from promotion p where p.chain_id = :chain and p.source = 'flyer' "
            "and exists (select 1 from promotion_target pt "
            "where pt.promotion_id = p.id and pt.chain_product_id = :product)"
        ),
        {"chain": chain_id, "product": product_id},
    )


def _apply_controlled_staple_retention(
    session: Session,
    *,
    chain_id: int,
    zone_id: int,
    run_id: int,
    observation_time: datetime,
) -> int:
    """Keep unseen flyer staples available at their reference price; drop everything else.

    A product the run did not see keeps selling while its last sighting is within the 21-day
    TTL and its latest flyer promotion recorded a reference price, and only if it is a
    private-label staple: `price_current` reverts to the reference price, closing the offer
    interval in `price_history`. `last_seen` is never bumped, so the TTL clock keeps ticking
    from the real last sighting. Anything else (expired, temporary, non-staple or without a
    reference price) is marked unavailable, and products with no available zone are
    deactivated. Returns how many prices the retention changed.
    """
    rows = session.execute(
        text(
            "select p.id, p.chain_sku as sku, p.name, p.packaging, p.url, p.image_url, "
            "p.base_quantity, p.base_unit, p.pack_count, z.last_seen, "
            "(select pr.reference_price from promotion pr "
            "join promotion_target pt on pt.promotion_id = pr.id "
            "join promotion_zone pz on pz.promotion_id = pr.id "
            "where pt.chain_product_id = p.id and pz.zone_id = :zone "
            "and pr.source = 'flyer' and pr.reference_price is not null "
            "order by pr.id desc limit 1) as reference_price "
            "from chain_product p "
            "join chain_product_zone z on z.chain_product_id = p.id "
            "where p.chain_id = :chain and z.zone_id = :zone "
            "and z.is_available and z.last_seen < :observed"
        ),
        {"chain": chain_id, "zone": zone_id, "observed": observation_time},
    ).all()
    prices_changed = 0
    for row in rows:
        (
            product_id,
            sku,
            name,
            packaging,
            url,
            image_url,
            base_quantity,
            base_unit,
            pack_count,
            last_seen,
            reference_price,
        ) = row
        within_ttl = (observation_time - last_seen) <= STAPLE_RETENTION_TTL
        if within_ttl and reference_price is not None and is_retendable_staple_name(name):
            # Keep it available at the recorded regular price; the TTL clock keeps ticking
            # because `last_seen` is not refreshed here.
            reg_ppu: Decimal | None = None
            if (
                base_quantity is not None
                and base_unit is not None
                and base_quantity * pack_count > 0
            ):
                reg_ppu = (reference_price / (base_quantity * pack_count)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
            prices_changed += _update_price(
                session,
                product_id=product_id,
                zone_id=zone_id,
                product=ProductObservation(
                    sku=sku,
                    name=name,
                    packaging=packaging,
                    url=url,
                    category_code="",
                    base_quantity=base_quantity,
                    base_unit=base_unit,
                    pack_count=pack_count,
                    price=reference_price,
                    price_per_unit=reg_ppu,
                    image_url=image_url,
                ),
                run_id=run_id,
                observation_time=observation_time,
            )
        else:
            session.execute(
                text(
                    "update chain_product_zone set is_available = false "
                    "where chain_product_id = :product and zone_id = :zone"
                ),
                {"product": product_id, "zone": zone_id},
            )
    session.execute(
        text(
            "update chain_product p set is_active = false "
            "where p.chain_id = :chain and p.is_active and not exists ("
            "select 1 from chain_product_zone z "
            "where z.chain_product_id = p.id and z.is_available)"
        ),
        {"chain": chain_id},
    )
    return prices_changed
