"""Basket optimizer and effective price: pure, deterministic, no database or network access.

Decisions 0002 (layer 3), 0007 (point 6), 0010 and 0013; requirements FR-09, FR-13, NFR-03.
"""

from smart_basket.optimizer.basket import ENGINE_VERSION, best_route, optimize
from smart_basket.optimizer.models import (
    LAMBDA_PRESETS,
    BaseUnit,
    BasketRequest,
    BasketResult,
    CoverRule,
    Line,
    LinePreferences,
    LinePurchase,
    MissingLine,
    MissingReason,
    OptimizerConfig,
    PackPurchase,
    PriorityMode,
    Product,
    Promotion,
    PromotionKind,
    Store,
    StorePurchase,
    Target,
    TargetKind,
    TravelTimes,
    Unit,
    VolumeTier,
)
from smart_basket.optimizer.packs import LineOption, cover_line
from smart_basket.optimizer.pricing import PricedLine, PricingContext, effective_price

__all__ = [
    "ENGINE_VERSION",
    "LAMBDA_PRESETS",
    "BaseUnit",
    "BasketRequest",
    "BasketResult",
    "CoverRule",
    "Line",
    "LineOption",
    "LinePreferences",
    "LinePurchase",
    "MissingLine",
    "MissingReason",
    "OptimizerConfig",
    "PackPurchase",
    "PricedLine",
    "PricingContext",
    "PriorityMode",
    "Product",
    "Promotion",
    "PromotionKind",
    "Store",
    "StorePurchase",
    "Target",
    "TargetKind",
    "TravelTimes",
    "Unit",
    "VolumeTier",
    "best_route",
    "cover_line",
    "effective_price",
    "optimize",
]
