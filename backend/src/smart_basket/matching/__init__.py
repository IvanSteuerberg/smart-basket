"""Rule-based product classifier: chain products to canonical products (task E2 of iteration 12).

Decisions 0004, 0007 and 0015: a leaf of the seed taxonomy plus the variants that change the
equivalence, with a review queue for everything the rules cannot decide.
"""

from smart_basket.matching.catalog import (
    DecisionFileError,
    DecisionsSummary,
    LeafReport,
    MatchResult,
    MatchSummary,
    ReviewItem,
    Taxonomy,
    export_decisions,
    export_review,
    import_decisions,
    load_products,
    load_taxonomy,
    pending_reviews,
    run,
    section_paths,
    sync_decisions,
    write_json,
)
from smart_basket.matching.names import Hit, NameMatch, canonical_name, name_match, variant_key
from smart_basket.matching.rules import Candidate, Decision, Section, decide

__all__ = [
    "Candidate",
    "Decision",
    "DecisionFileError",
    "DecisionsSummary",
    "Hit",
    "LeafReport",
    "MatchResult",
    "MatchSummary",
    "NameMatch",
    "ReviewItem",
    "Section",
    "Taxonomy",
    "canonical_name",
    "decide",
    "export_decisions",
    "export_review",
    "import_decisions",
    "load_products",
    "load_taxonomy",
    "name_match",
    "pending_reviews",
    "run",
    "section_paths",
    "sync_decisions",
    "variant_key",
    "write_json",
]
