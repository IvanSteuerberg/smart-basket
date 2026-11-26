"""Fill product photos from the raw responses already archived, without crawling again.

A response is kept gzipped under `DATA_DIR` for every crawl, so the photos of the products
collected before the adapter read `thumbnail` are still in those files. The newest response that
mentions a SKU wins, as in a crawl, and later crawls keep the column current.
"""

import gzip
import json
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.db import session_scope
from smart_basket.ingestion.mercadona import iter_product_images
from smart_basket.ingestion.quality import (
    derived_price_per_unit,
    extract_dietary_tags,
    normalize_image_url,
    reparse_multipack_from_name,
    sanitize_unit_pricing,
)

log = logging.getLogger("smart_basket.ingestion")

# How to find the photos inside the archived body of each chain.
IMAGE_EXTRACTORS: dict[str, Callable[[Mapping[str, Any]], Iterator[tuple[str, str]]]] = {
    "mercadona": iter_product_images,
}

# Rows per update statement, so a large catalog does not send one huge batch.
UPDATE_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class ImageBackfillSummary:
    """What one backfill did, for the caller to log and for tests to assert."""

    updated: int
    unchanged: int
    missing: int
    responses_skipped: int

    def message(self) -> str:
        """The one-line summary the CLI prints."""
        return (
            f"images: {self.updated} updated, {self.unchanged} unchanged, "
            f"{self.missing} without image"
        )


def backfill_images(
    chain_code: str, *, data_dir: Path, database_url: str | None = None
) -> ImageBackfillSummary:
    """Give every active product of `chain_code` the photo of the newest archived response."""
    extractor = IMAGE_EXTRACTORS.get(chain_code)
    if extractor is None:
        raise ValueError(f"no image extractor for chain '{chain_code}'")

    with session_scope(database_url) as session:
        products = session.execute(
            text(
                "select p.id, p.chain_sku, p.image_url from chain_product p "
                "join chain c on c.id = p.chain_id "
                "where c.code = :chain and p.is_active order by p.id"
            ),
            {"chain": chain_code},
        ).all()
        response_paths = (
            session.execute(
                text(
                    "select r.path from raw_response r "
                    "join ingest_run i on i.id = r.run_id "
                    "join chain c on c.id = i.chain_id "
                    "where c.code = :chain order by r.fetched_at desc, r.id desc"
                ),
                {"chain": chain_code},
            )
            .scalars()
            .all()
        )

    images, responses_skipped = _images_from_archive(
        response_paths,
        targets={row.chain_sku for row in products},
        data_dir=data_dir,
        extractor=extractor,
    )

    updated = unchanged = missing = 0
    updates: list[dict[str, Any]] = []
    for row in products:
        image = images.get(row.chain_sku)
        if image is None:
            missing += 1
        elif image == row.image_url:
            unchanged += 1
        else:
            updates.append({"image": image, "id": row.id})
            updated += 1

    if updates:
        with session_scope(database_url) as session:
            for start in range(0, len(updates), UPDATE_BATCH_SIZE):
                session.execute(
                    text("update chain_product set image_url = :image where id = :id"),
                    updates[start : start + UPDATE_BATCH_SIZE],
                )

    return ImageBackfillSummary(
        updated=updated,
        unchanged=unchanged,
        missing=missing,
        responses_skipped=responses_skipped,
    )


@dataclass(frozen=True, slots=True)
class CatalogQualityBackfillSummary:
    """What one catalog-quality backfill did, for the caller to log and for idempotency."""

    products: int
    multipacks_fixed: int
    outliers_sanitized: int
    dietary_tagged: int
    images_normalized: int = 0

    def message(self) -> str:
        """The one-line summary the CLI prints."""
        text_ = (
            f"catalog quality: {self.products} products, "
            f"{self.multipacks_fixed} multipacks fixed, "
            f"{self.outliers_sanitized} unit-price outliers sanitized, "
            f"{self.dietary_tagged} dietary tag sets filled"
        )
        if self.images_normalized:
            text_ += f", {self.images_normalized} image URLs normalized"
        return text_


def backfill_catalog_quality(
    target: Session | str | None = None,
) -> CatalogQualityBackfillSummary:
    """Sanitize the rows already stored, without crawling again (A1 and FR-42).

    Reparses multipack sizes hidden in the name, repairs or clears impossible unit prices and
    fills `dietary_tags` from the explicit declarations of the name and packaging. Running it
    twice changes nothing the second time. `target` is a session (the caller owns its
    transaction) or a database URL.
    """
    if isinstance(target, Session):
        return _backfill_catalog_quality(target)
    with session_scope(target) as session:
        return _backfill_catalog_quality(session)


def _backfill_catalog_quality(session: Session) -> CatalogQualityBackfillSummary:
    rows = session.execute(
        text(
            "select p.id as product_id, p.name, p.packaging, p.base_quantity, p.base_unit, "
            "p.pack_count, p.dietary_tags, p.image_url, c.zone_id, c.price, c.price_per_unit "
            "from chain_product p "
            "left join price_current c on c.chain_product_id = p.id "
            "where p.is_active order by p.id, c.zone_id"
        )
    ).all()
    grouped: dict[int, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.product_id, []).append(row)

    multipacks_fixed = outliers_sanitized = dietary_tagged = images_normalized = 0
    for product_id, price_rows in grouped.items():
        first = price_rows[0]
        name = first.name
        quantity, unit, pack_count = first.base_quantity, first.base_unit, first.pack_count
        name_quantity, name_unit, name_pack = reparse_multipack_from_name(name)
        multipack_fixed = pack_count == 1 and name_pack > 1
        if multipack_fixed:
            if name_quantity is not None and name_unit not in (None, "ud"):
                quantity, unit = name_quantity, name_unit
            pack_count = name_pack

        sanitized = False
        price_updates: list[tuple[int, Decimal | None]] = []
        for price_row in price_rows:
            if price_row.zone_id is None:
                continue
            candidate = price_row.price_per_unit
            if multipack_fixed:
                candidate = derived_price_per_unit(price_row.price, quantity, unit, pack_count)
            pricing = sanitize_unit_pricing(
                name,
                price_row.price,
                quantity,
                unit,
                pack_count,
                price_per_unit=candidate,
            )
            if pricing.repaired:
                sanitized = True
                quantity, unit, pack_count = (
                    pricing.base_quantity,
                    pricing.base_unit,
                    pricing.pack_count,
                )
            if pricing.price_per_unit != price_row.price_per_unit:
                price_updates.append((price_row.zone_id, pricing.price_per_unit))

        tags = extract_dietary_tags(name, first.packaging)
        tags_changed = tags != tuple(first.dietary_tags or ())
        image = normalize_image_url(first.image_url)
        image_changed = image != first.image_url
        if multipack_fixed:
            multipacks_fixed += 1
        if sanitized:
            outliers_sanitized += 1
        if tags_changed:
            dietary_tagged += 1
        if image_changed:
            images_normalized += 1
        if not (multipack_fixed or sanitized or tags_changed or image_changed):
            continue
        session.execute(
            text(
                "update chain_product set base_quantity = :quantity, base_unit = :unit, "
                "pack_count = :pack_count, dietary_tags = :tags, image_url = :image "
                "where id = :product"
            ),
            {
                "product": product_id,
                "image": image,
                "quantity": quantity,
                "unit": unit,
                "pack_count": pack_count,
                "tags": list(tags),
            },
        )
        for zone_id, price_per_unit in price_updates:
            session.execute(
                text(
                    "update price_current set price_per_unit = :price_per_unit "
                    "where chain_product_id = :product and zone_id = :zone"
                ),
                {"product": product_id, "zone": zone_id, "price_per_unit": price_per_unit},
            )

    return CatalogQualityBackfillSummary(
        products=len(grouped),
        multipacks_fixed=multipacks_fixed,
        outliers_sanitized=outliers_sanitized,
        dietary_tagged=dietary_tagged,
        images_normalized=images_normalized,
    )


def _images_from_archive(
    response_paths: Iterable[str],
    *,
    targets: set[str],
    data_dir: Path,
    extractor: Callable[[Mapping[str, Any]], Iterator[tuple[str, str]]],
) -> tuple[dict[str, str], int]:
    """Map each target SKU to the photo of the newest response that mentions it.

    Responses are read newest first, so the first sighting of a SKU is the one kept. Files that
    are missing or unreadable are counted and skipped with a warning: one lost archive entry must
    not stop the backfill. A path that resolves outside `data_dir` is skipped the same way, so a
    bad row can never make the backfill read the rest of the disk.
    """
    root = data_dir.resolve()
    images: dict[str, str] = {}
    skipped = 0
    read: set[str] = set()
    for path in response_paths:
        if path in read:
            continue
        read.add(path)
        if len(images) == len(targets):
            break
        file = (root / path).resolve()
        if not file.is_relative_to(root):
            skipped += 1
            log.warning("skipping raw response outside the data directory %s", path)
            continue
        payload = _read_response(file)
        if payload is None:
            skipped += 1
            log.warning("skipping missing or unreadable raw response %s", path)
            continue
        for sku, image in extractor(payload):
            if sku in targets and sku not in images:
                images[sku] = image
    return images, skipped


def _read_response(path: Path) -> Mapping[str, Any] | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as body:
            payload = json.load(body)
    except OSError, ValueError, EOFError:
        return None
    return payload if isinstance(payload, Mapping) else None
