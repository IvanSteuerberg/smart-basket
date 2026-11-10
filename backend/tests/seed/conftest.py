"""Shared fixtures of the seed tests."""

from pathlib import Path

import pytest

SEED_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "seed"


@pytest.fixture
def seed_dir() -> Path:
    """A small synthetic seed: two chains and a two-branch taxonomy."""
    return SEED_FIXTURES
