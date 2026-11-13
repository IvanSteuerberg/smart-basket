"""Process-wide preprocessor built from the seeded catalog.

Building the lexicon reads the catalog and the packaged variants, so it is done once per
process and redone only when a cheap fingerprint of the seed changes, checked at most every
minute (decision 0014).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.preprocessor import Preprocessor
from smart_basket.preprocessor.text import fold
from smart_basket.vocabulary import build_lexicon

CHECK_INTERVAL_SECONDS = 60.0

#: Content hashes as well as counts: a renamed category, changed forms or `is_vague`, or an
#: edited brand must refresh the lexicon even when no row was added or removed.
_FINGERPRINT_SQL = text(
    "select (select count(*) from category) as categories,"
    " (select coalesce(md5(string_agg("
    "    key || '|' || name || '|' || array_to_string(forms, '|') || '|' || is_vague::text,"
    "    ',' order by id)), '') from category) as categories_hash,"
    " (select count(*) from brand) as brands,"
    " (select coalesce(md5(string_agg("
    "    name || '|' || is_private_label::text, ',' order by id)), '') from brand) as brands_hash"
)

#: Folded name and forms of every category, computed when the lexicon is rebuilt.
_CATEGORY_FORMS_SQL = text("select id, name, forms from category")

Fingerprint = tuple[int, str, int, str]


def _fingerprint(session: Session) -> Fingerprint:
    row = session.execute(_FINGERPRINT_SQL).one()
    return (row.categories, row.categories_hash, row.brands, row.brands_hash)


def _category_forms(session: Session) -> dict[int, tuple[str, ...]]:
    return {
        row.id: (fold(row.name), *(fold(form) for form in row.forms))
        for row in session.execute(_CATEGORY_FORMS_SQL)
    }


class LexiconCache:
    """A `Preprocessor` shared by the process, rebuilt when the seed fingerprint changes."""

    def __init__(
        self,
        check_interval: float = CHECK_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.check_interval = check_interval
        self._clock = clock
        self._lock = threading.Lock()
        self._preprocessor: Preprocessor | None = None
        self._fingerprint: Fingerprint | None = None
        self._checked = 0.0
        self._forms: dict[int, tuple[str, ...]] | None = None
        self._forms_fingerprint: Fingerprint | None = None
        self._forms_checked = 0.0

    def preprocessor(self, session: Session) -> Preprocessor:
        """The cached preprocessor, checking the fingerprint at most every `check_interval`."""
        with self._lock:
            now = self._clock()
            if self._preprocessor is not None and now - self._checked < self.check_interval:
                return self._preprocessor
            fingerprint = _fingerprint(session)
            if self._preprocessor is None or fingerprint != self._fingerprint:
                self._preprocessor = Preprocessor(build_lexicon(session))
                self._fingerprint = fingerprint
            self._checked = now
            return self._preprocessor

    def search_forms(self, session: Session) -> dict[int, tuple[str, ...]]:
        """Folded name and forms of every category, refreshed with the same fingerprint."""
        with self._lock:
            now = self._clock()
            if self._forms is not None and now - self._forms_checked < self.check_interval:
                return self._forms
            fingerprint = _fingerprint(session)
            if self._forms is None or fingerprint != self._forms_fingerprint:
                self._forms = _category_forms(session)
                self._forms_fingerprint = fingerprint
            self._forms_checked = now
            return self._forms

    def reset(self) -> None:
        """Forget the cached preprocessor; tests call it between databases."""
        with self._lock:
            self._preprocessor = None
            self._fingerprint = None
            self._checked = 0.0
            self._forms = None
            self._forms_fingerprint = None
            self._forms_checked = 0.0


default_cache = LexiconCache()


def preprocessor_for(session: Session) -> Preprocessor:
    """The process-wide preprocessor, built from `session`'s catalog on first use."""
    return default_cache.preprocessor(session)


def search_forms_for(session: Session) -> dict[int, tuple[str, ...]]:
    """The process-wide folded category forms, built from `session`'s catalog on first use."""
    return default_cache.search_forms(session)
