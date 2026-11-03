"""Input and output types of the basket optimizer. Pure data: no database or network access.

Money is `Decimal` in euros, quantities are `Decimal` in the units given, travel times are
`Decimal` minutes. Every type is immutable so a request can be hashed, cached and replayed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Unit(StrEnum):
    """Units a list line can use (same set as the LLM item schema)."""

    UD = "ud"
    KG = "kg"
    G = "g"
    L = "l"
    ML = "ml"


class BaseUnit(StrEnum):
    """Base units of canonical and chain products (data model: `base_unit`)."""

    UD = "ud"
    KG = "kg"
    L = "l"


#: Each line unit in terms of a base unit.
UNIT_TO_BASE: dict[Unit, tuple[BaseUnit, Decimal]] = {
    Unit.UD: (BaseUnit.UD, Decimal(1)),
    Unit.KG: (BaseUnit.KG, Decimal(1)),
    Unit.G: (BaseUnit.KG, Decimal("0.001")),
    Unit.L: (BaseUnit.L, Decimal(1)),
    Unit.ML: (BaseUnit.L, Decimal("0.001")),
}


class PromotionKind(StrEnum):
    """Promotion mechanics of the data model (`promotion.kind`)."""

    PROMO_PRICE = "promo_price"
    PERCENT_OFF = "percent_off"
    NXM = "nxm"
    SECOND_UNIT = "second_unit"
    VOLUME_TIER = "volume_tier"
    LOYALTY_PRICE = "loyalty_price"
    COUPON = "coupon"


class TargetKind(StrEnum):
    """What a promotion applies to (`promotion_target`)."""

    PRODUCT = "chain_product"
    CANONICAL = "canonical"
    CATEGORY = "category"
    BRAND = "brand"


class PriorityMode(StrEnum):
    """Money-versus-time trade-off chosen by the user (FR-09)."""

    SAVINGS = "savings"
    BALANCED = "balanced"
    TIME = "time"


#: Starting values of lambda in euros per minute (FR-09): 3, 9 and 24 €/h.
LAMBDA_PRESETS: dict[PriorityMode, Decimal] = {
    PriorityMode.SAVINGS: Decimal("0.05"),
    PriorityMode.BALANCED: Decimal("0.15"),
    PriorityMode.TIME: Decimal("0.40"),
}


class MissingReason(StrEnum):
    """Why a line is not in the basket (FR-21)."""

    #: No candidate store sells a product that satisfies the line.
    NOT_AVAILABLE = "not_available"
    #: Some candidate store sells it, but none of the chosen stores does (max stores limit).
    STORE_LIMIT = "store_limit"


class CoverRule(StrEnum):
    """How the quantity of a line was covered with packs."""

    #: Pack-covering rule of decision 0010 (80-150 % band, price per base unit, near ties).
    COVER = "cover"
    #: Exact brand or format requested (FR-04): one product, fewest packs reaching the quantity.
    EXACT = "exact"
    #: Count of packs without a known size per unit: the cheapest product, `quantity` packs.
    PACK_COUNT = "pack_count"
    #: No combination falls in the band: the cheapest single product reaching the quantity.
    FALLBACK = "fallback"


@dataclass(frozen=True, slots=True)
class OptimizerConfig:
    """Thresholds of decision 0010 and search limits (decision 0013)."""

    band_min: Decimal = Decimal("0.80")
    band_max: Decimal = Decimal("1.50")
    near_tie: Decimal = Decimal("0.05")
    #: Distinct products mixed to cover one line in one store (e.g. a 1 kg and a 500 g pack).
    max_distinct_products: int = 2

    def __post_init__(self) -> None:
        if not (0 < self.band_min <= 1 <= self.band_max):
            raise ValueError("band must satisfy 0 < band_min <= 1 <= band_max")
        if self.near_tie < 0:
            raise ValueError("near_tie must be >= 0")
        if self.max_distinct_products < 1:
            raise ValueError("max_distinct_products must be >= 1")


@dataclass(frozen=True, slots=True)
class Target:
    kind: TargetKind
    id: int


@dataclass(frozen=True, slots=True)
class VolumeTier:
    """From `min_units` units on, every unit costs `unit_price`, or `percent` less."""

    min_units: int
    unit_price: Decimal | None = None
    percent: Decimal | None = None

    def __post_init__(self) -> None:
        if self.min_units < 1 or (self.unit_price is None) == (self.percent is None):
            raise ValueError("a tier needs min_units >= 1 and exactly one of unit_price, percent")


@dataclass(frozen=True, slots=True)
class Promotion:
    """A promotion of the store's chain, with its targets and validity.

    `valid_to` is exclusive (as a PostgreSQL `daterange`); `None` means open-ended.
    `zone_ids` empty means the whole chain. `percent` is the discount in percent, also for
    `second_unit` ("2ª unidad al 50 %" → percent 50).
    """

    promotion_id: int
    kind: PromotionKind
    targets: tuple[Target, ...]
    valid_from: date
    valid_to: date | None = None
    promo_price: Decimal | None = None
    percent: Decimal | None = None
    amount: Decimal | None = None
    buy_n: int | None = None
    pay_m: int | None = None
    tiers: tuple[VolumeTier, ...] = ()
    requires_loyalty: bool = False
    coupon_code: str | None = None
    applied_in_price: bool = False
    priority: int = 0
    zone_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        k = self.kind
        ok = {
            PromotionKind.PROMO_PRICE: self.promo_price is not None,
            PromotionKind.LOYALTY_PRICE: self.promo_price is not None and self.requires_loyalty,
            PromotionKind.PERCENT_OFF: self.percent is not None,
            PromotionKind.SECOND_UNIT: self.percent is not None,
            PromotionKind.NXM: (
                self.buy_n is not None and self.pay_m is not None and 1 <= self.pay_m < self.buy_n
            ),
            PromotionKind.VOLUME_TIER: len(self.tiers) > 0,
            PromotionKind.COUPON: (
                self.coupon_code is not None and (self.amount is None) != (self.percent is None)
            ),
        }[k]
        if not ok:
            raise ValueError(f"promotion {self.promotion_id}: missing parameters for {k}")
        if self.percent is not None and not (0 < self.percent <= 100):
            raise ValueError(f"promotion {self.promotion_id}: percent must be in (0, 100]")
        if not self.targets:
            raise ValueError(f"promotion {self.promotion_id}: needs at least one target")

    def is_valid_on(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day < self.valid_to)


@dataclass(frozen=True, slots=True)
class Product:
    """A chain product as sold in a store, with its observed price on the shopping date.

    One pack holds `pack_count` units of `base_quantity` each (a 6 x 1 l pack of milk is
    base_quantity 1, pack_count 6). `category_ids` holds the product's category and all its
    ancestors, so category promotions match descendants.
    """

    product_id: int
    canonical_id: int
    price: Decimal
    base_quantity: Decimal
    base_unit: BaseUnit
    pack_count: int = 1
    brand_id: int | None = None
    is_private_label: bool = False
    category_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.price < 0 or self.base_quantity <= 0 or self.pack_count < 1:
            raise ValueError(f"product {self.product_id}: invalid price or size")

    @property
    def net_quantity(self) -> Decimal:
        return self.base_quantity * self.pack_count


@dataclass(frozen=True, slots=True)
class Store:
    store_id: int
    chain_id: int
    products: tuple[Product, ...]
    promotions: tuple[Promotion, ...] = ()
    zone_id: int | None = None


@dataclass(frozen=True, slots=True)
class LinePreferences:
    """Per-line preferences (FR-04). Brand or format makes the line exact (0010, point 5)."""

    brand_id: int | None = None
    #: Exact format: the pack's net quantity in the product's base unit (e.g. 1.5 for 1.5 l).
    pack_quantity: Decimal | None = None
    private_label_ok: bool = True

    @property
    def exact(self) -> bool:
        return self.brand_id is not None or self.pack_quantity is not None


@dataclass(frozen=True, slots=True)
class Line:
    """An interpreted list line resolved to a canonical product.

    `default_quantity` is the canonical product's usual quantity per unit in its base unit
    (`canonical_product.default_quantity`), used when the line counts units ("ud") of a product
    sold by weight or volume: "6 bricks de leche" with default 1 l asks for 6 l.
    """

    line_id: str
    canonical_id: int
    quantity: Decimal
    unit: Unit = Unit.UD
    preferences: LinePreferences = field(default_factory=LinePreferences)
    default_quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"line {self.line_id}: quantity must be positive")


@dataclass(frozen=True, slots=True)
class TravelTimes:
    """Travel-time matrix from the routing interface: index 0 is the origin, then `store_ids`.

    `minutes[i][j]` is the time from node i to node j; `None` means unreachable.
    """

    store_ids: tuple[int, ...]
    minutes: tuple[tuple[Decimal | None, ...], ...]

    def __post_init__(self) -> None:
        n = len(self.store_ids) + 1
        if len(self.minutes) != n or any(len(row) != n for row in self.minutes):
            raise ValueError("travel-time matrix must be square: origin plus each store")
        if len(set(self.store_ids)) != len(self.store_ids):
            raise ValueError("duplicate store in travel-time matrix")


@dataclass(frozen=True, slots=True)
class BasketRequest:
    lines: tuple[Line, ...]
    stores: tuple[Store, ...]
    travel_times: TravelTimes
    shopping_date: date
    max_stores: int = 3
    priority_mode: PriorityMode = PriorityMode.BALANCED
    #: Explicit lambda in €/min; when None the preset of `priority_mode` is used.
    lambda_per_minute: Decimal | None = None
    loyalty_chain_ids: frozenset[int] = frozenset()
    coupon_codes: frozenset[str] = frozenset()
    return_to_origin: bool = True
    config: OptimizerConfig = field(default_factory=OptimizerConfig)

    def __post_init__(self) -> None:
        if not 1 <= self.max_stores <= 3:
            raise ValueError("max_stores must be between 1 and 3 (FR-08)")
        if self.lambda_per_minute is not None and self.lambda_per_minute < 0:
            raise ValueError("lambda must be >= 0")
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate line_id")
        if len({s.store_id for s in self.stores}) != len(self.stores):
            raise ValueError("duplicate store_id")

    @property
    def effective_lambda(self) -> Decimal:
        if self.lambda_per_minute is not None:
            return self.lambda_per_minute
        return LAMBDA_PRESETS[self.priority_mode]


# Results ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PackPurchase:
    product_id: int
    packs: int
    quantity: Decimal
    cost: Decimal
    promotion_id: int | None = None
    promotion_kind: PromotionKind | None = None


@dataclass(frozen=True, slots=True)
class LinePurchase:
    line_id: str
    canonical_id: int
    base_unit: BaseUnit
    rule: CoverRule
    #: Requested quantity in the base unit; None for pack counts without a size per unit.
    quantity_requested: Decimal | None
    quantity_bought: Decimal
    cost: Decimal
    #: Cost used to compare stores: price per base unit x requested quantity (decision 0013).
    comparable_cost: Decimal
    packs: tuple[PackPurchase, ...]


@dataclass(frozen=True, slots=True)
class StorePurchase:
    store_id: int
    chain_id: int
    position: int
    lines: tuple[LinePurchase, ...]
    subtotal: Decimal


@dataclass(frozen=True, slots=True)
class MissingLine:
    line_id: str
    reason: MissingReason


@dataclass(frozen=True, slots=True)
class BasketResult:
    engine_version: str
    stores: tuple[StorePurchase, ...]
    total_cost: Decimal
    comparable_cost: Decimal
    minutes: Decimal
    lambda_per_minute: Decimal
    objective: Decimal
    priority_mode: PriorityMode
    max_stores: int
    return_to_origin: bool
    missing: tuple[MissingLine, ...]

    @property
    def visiting_order(self) -> tuple[int, ...]:
        return tuple(s.store_id for s in self.stores)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self) | {"visiting_order": list(self.visiting_order)}

    def to_json(self) -> str:
        """Canonical JSON: sorted keys, decimals as strings, so equal results are equal bytes."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return {name: _plain(getattr(value, name)) for name in value.__dataclass_fields__}
    return value
