import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def load_fixture() -> Callable[[str], dict[str, Any]]:
    """Read one of the small synthetic API responses kept next to the tests."""

    def load(name: str) -> dict[str, Any]:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return load
