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
from smart_basket.vocabulary import build_lexicon

CHECK_INTERVAL_SECONDS = 60.0

_FINGERPRINT_SQL = text(
    "select (select count(*) from category) as categories,"
    " (select coalesce(max(id), 0) from category) as last_category,"
    " (select count(*) from brand) as brands,"
    " (select coalesce(max(id), 0) from brand) as last_brand"
)

Fingerprint = tuple[int, int, int, int]


def _fingerprint(session: Session) -> Fingerprint:
    row = session.execute(_FINGERPRINT_SQL).one()
    return (row.categories, row.last_category, row.brands, row.last_brand)


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

    def reset(self) -> None:
        """Forget the cached preprocessor; tests call it between databases."""
        with self._lock:
            self._preprocessor = None
            self._fingerprint = None
            self._checked = 0.0


default_cache = LexiconCache()


def preprocessor_for(session: Session) -> Preprocessor:
    """The process-wide preprocessor, built from `session`'s catalog on first use."""
    return default_cache.preprocessor(session)
