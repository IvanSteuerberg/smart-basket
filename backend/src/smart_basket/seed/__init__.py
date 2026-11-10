"""Seed loader for chains, zones and the canonical category taxonomy (decision 0007)."""

from pathlib import Path

from smart_basket.seed.loader import SeedReport, load_seed

#: The real seed files are written by the seed data task and shipped inside the package.
DEFAULT_DATA_DIR = Path(__file__).parent / "data"

__all__ = ["DEFAULT_DATA_DIR", "SeedReport", "load_seed"]
