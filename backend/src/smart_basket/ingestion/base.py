"""What a chain adapter observes, independent of the chain and of the database.

The adapter yields observations while it crawls; `collect` folds them into one result so the
persistence layer never has to know which chain produced them (decision 0006, NFR-12).
"""

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

type BaseUnit = Literal["kg", "l", "ud"]
type RunStatus = Literal["running", "succeeded", "partial", "failed"]
type FinalStatus = Literal["succeeded", "partial", "failed"]


@dataclass(frozen=True, slots=True)
class CategoryObservation:
    """A category of the chain's tree; `parent_code` is None for the roots."""

    code: str
    name: str
    parent_code: str | None


@dataclass(frozen=True, slots=True)
class ProductObservation:
    """A product as sold by the chain, with its size and the price seen in one crawl."""

    sku: str
    name: str
    packaging: str | None
    url: str | None
    category_code: str
    base_quantity: Decimal | None
    base_unit: BaseUnit | None
    pack_count: int
    price: Decimal
    price_per_unit: Decimal | None


@dataclass(frozen=True, slots=True)
class RawResponse:
    """One HTTP response, kept so the store can archive it with the run (decision 0006)."""

    url: str
    status_code: int
    body: bytes


@dataclass(frozen=True, slots=True)
class CrawlError:
    """A request that failed, reported without aborting the rest of the crawl (NFR-09)."""

    url: str
    error: str


@dataclass(frozen=True, slots=True)
class SkippedProduct(CrawlError):
    """A product the parser dropped; a small share of them does not spoil the run."""


type Observation = CategoryObservation | ProductObservation | RawResponse | CrawlError


@dataclass(frozen=True, slots=True)
class CrawlResult:
    """Everything one crawl produced, deduplicated, plus how it ended."""

    categories: tuple[CategoryObservation, ...]
    products: tuple[ProductObservation, ...]
    raw: tuple[RawResponse, ...]
    errors: tuple[CrawlError, ...]
    status: FinalStatus
    complete: bool


class ChainAdapter(Protocol):
    """One adapter per chain (NFR-12): crawls a zone and yields what it observes."""

    chain_code: str

    def crawl(self, zone_code: str, *, max_categories: int | None = None) -> Iterator[Observation]:
        """Yield categories, products, raw responses and per-request errors for one zone."""
        ...


def collect(
    adapter: ChainAdapter, zone_code: str, *, max_categories: int | None = None
) -> CrawlResult:
    """Consume an adapter once, keeping the first sighting of every category and product.

    A failure that escapes the adapter (for example the category tree request) ends the run as
    `failed`; errors the adapter reports per request make it `partial`. Products the parser had
    to drop are recorded but tolerated at 1 % of those seen (at least one), so a single broken
    item does not spoil a whole catalog. A run is complete only when it was not limited and ended
    without hard errors and with at least one product, so a broken or empty crawl can never mark
    products unavailable.
    """

    categories: dict[str, CategoryObservation] = {}
    products: dict[str, ProductObservation] = {}
    raw: list[RawResponse] = []
    errors: list[CrawlError] = []
    skipped = 0
    hard_error = False
    failed = False
    try:
        for observation in adapter.crawl(zone_code, max_categories=max_categories):
            match observation:
                case SkippedProduct():
                    errors.append(observation)
                    skipped += 1
                case CategoryObservation():
                    categories.setdefault(observation.code, observation)
                case ProductObservation():
                    products.setdefault(observation.sku, observation)
                case RawResponse():
                    raw.append(observation)
                case CrawlError():
                    errors.append(observation)
                    hard_error = True
    except Exception as exc:  # a chain failure must not stop the run bookkeeping
        failed = True
        url = getattr(exc, "url", None) or zone_code
        errors.append(CrawlError(url=str(url), error=str(exc)))

    status: FinalStatus
    if failed:
        status = "failed"
    elif hard_error or skipped > _allowed_skips(len(products)):
        status = "partial"
    else:
        status = "succeeded"
    complete = status == "succeeded" and max_categories is None and bool(products)
    return CrawlResult(
        categories=tuple(categories.values()),
        products=tuple(products.values()),
        raw=tuple(raw),
        errors=tuple(errors),
        status=status,
        complete=complete,
    )


def _allowed_skips(products_seen: int) -> int:
    """Tolerate 1 % of the products seen as parser drops, and at least one in small catalogs."""
    return max(1, products_seen // 100)
