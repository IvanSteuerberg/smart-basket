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
from pathlib import Path
from typing import Any

from sqlalchemy import text

from smart_basket.db import session_scope
from smart_basket.ingestion.mercadona import iter_product_images

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
