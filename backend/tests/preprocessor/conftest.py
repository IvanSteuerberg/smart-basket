from pathlib import Path

import pytest

from smart_basket.preprocessor import InMemoryLexicon, Preprocessor

FIXTURE = Path(__file__).parents[1] / "fixtures" / "lexicon_es.json"


@pytest.fixture(scope="session")
def lexicon() -> InMemoryLexicon:
    return InMemoryLexicon.from_json(FIXTURE)


@pytest.fixture(scope="session")
def pp(lexicon) -> Preprocessor:
    return Preprocessor(lexicon)


@pytest.fixture
def one(pp):
    """Preprocess a single-line list and return its only item."""

    def run(text: str):
        items = pp.preprocess(text).items
        assert len(items) == 1, [i.item for i in items]
        return items[0]

    return run
