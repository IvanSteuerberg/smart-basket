"""Brand names, aliases and private labels found in product names.

The recommender and the product catalog deduce a product's brand the same way: a brand name
(when `match_name` allows it) or one of its aliases appears as whole folded words of the product
name. The table is small, so the catalog keeps the loaded brands for the whole process and
rebuilds them when a cheap fingerprint changes, as the lexicon cache does.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.preprocessor.text import fold, words

#: Columns of `brand`; `aliases` and `match_name` may be missing in an older database.
_BRAND_COLUMNS_SQL = text(
    "select column_name from information_schema.columns where table_name = 'brand'"
)

#: Count and content hash of the brands, cheap enough to check on every request window.
_FINGERPRINT_SQL = text(
    "select (select count(*) from brand) as brands,"
    " (select coalesce(md5(string_agg("
    "    name || '|' || array_to_string(aliases, ';') || '|' || is_private_label::text"
    "    || '|' || coalesce(owner_chain_id::text, '') || '|' || match_name::text,"
    "    ',' order by id)), '') from brand) as brands_hash"
)

CHECK_INTERVAL_SECONDS = 60.0

Fingerprint = tuple[int, str]


def contains_words(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """True when `needle` appears as a run of whole tokens in `haystack`."""
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[start : start + len(needle)] == needle
        for start in range(len(haystack) - len(needle) + 1)
    )


def matches_brand(name: str, terms: Iterable[str]) -> bool:
    """True when a brand name or alias appears as whole words of the product name."""
    product_words = words(name)
    return any(contains_words(product_words, words(term)) for term in terms)


class Brands:
    """Brand names, their aliases and the private labels of each chain."""

    def __init__(self, session: Session) -> None:
        columns = set(session.execute(_BRAND_COLUMNS_SQL).scalars())
        # A database from before migration 0004 has neither column: only the name is used.
        alias = "aliases" if "aliases" in columns else "null::text[] as aliases"
        match = "match_name" if "match_name" in columns else "true as match_name"
        self._aliases: dict[str, tuple[str, ...]] = {}
        self._private_labels: dict[int, list[tuple[str, ...]]] = {}
        #: Brand terms usable to deduce a brand from a product name: (words, display name, id).
        self._terms: list[tuple[tuple[str, ...], str, int]] = []
        for row in session.execute(
            text(f"select id, name, {alias}, is_private_label, owner_chain_id, {match} from brand")
        ).mappings():
            folded = fold(row["name"])
            aliases = tuple(fold(value) for value in (row["aliases"] or ()))
            terms = (folded, *aliases)
            # A brand written as an alias must reach the same terms as its name.
            self._aliases[folded] = terms
            for value in aliases:
                self._aliases[value] = terms
            if row["is_private_label"] and row["owner_chain_id"] is not None:
                self._private_labels.setdefault(row["owner_chain_id"], []).append(
                    words(row["name"])
                )
            if row["match_name"]:
                self._terms.append((words(row["name"]), row["name"], row["id"]))
            for value in aliases:
                self._terms.append((words(value), row["name"], row["id"]))

    def terms(self, brand: str) -> set[str]:
        """The folded brand name and the aliases of the matching brand."""
        target = fold(brand)
        return {target, *self._aliases.get(target, ())}

    def brand_for(self, product_name: str) -> str | None:
        """The most specific brand named by the product, or None when it names no brand.

        "Carrefour Bio" wins over "Carrefour" when both match; ties keep the lowest brand id.
        """
        product_words = words(product_name)
        best: tuple[tuple[int, int, int], str] | None = None
        for term, name, brand_id in self._terms:
            if not contains_words(product_words, term):
                continue
            rank = (len(term), sum(len(word) for word in term), -brand_id)
            if best is None or rank > best[0]:
                best = (rank, name)
        return best[1] if best is not None else None

    def is_private_label(self, chain_id: int, product_name: str) -> bool:
        """True when the product name has one of its chain's private labels as whole words."""
        product_words = words(product_name)
        return any(
            contains_words(product_words, label) for label in self._private_labels.get(chain_id, ())
        )


class BrandCache:
    """A `Brands` shared by the process, rebuilt when the brand fingerprint changes."""

    def __init__(
        self,
        check_interval: float = CHECK_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.check_interval = check_interval
        self._clock = clock
        self._lock = threading.Lock()
        self._brands: Brands | None = None
        self._fingerprint: Fingerprint | None = None
        self._checked = 0.0

    def brands(self, session: Session) -> Brands:
        """The cached brands, checking the fingerprint at most every `check_interval`."""
        with self._lock:
            now = self._clock()
            if self._brands is not None and now - self._checked < self.check_interval:
                return self._brands
            fingerprint = _fingerprint(session)
            if self._brands is None or fingerprint != self._fingerprint:
                self._brands = Brands(session)
                self._fingerprint = fingerprint
            self._checked = now
            return self._brands

    def reset(self) -> None:
        """Forget the cached brands; tests call it between databases."""
        with self._lock:
            self._brands = None
            self._fingerprint = None
            self._checked = 0.0


def _fingerprint(session: Session) -> Fingerprint:
    row = session.execute(_FINGERPRINT_SQL).one()
    return (row.brands, row.brands_hash)


default_cache = BrandCache()


def brands_for(session: Session) -> Brands:
    """The process-wide brands, built from `session`'s catalog on first use."""
    return default_cache.brands(session)
