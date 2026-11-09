"""The `smart-basket-seed` console entry point."""

import pytest

from smart_basket.seed.__main__ import main


def test_missing_data_dir_exits_with_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match="seed data directory not found"):
        main(["--data-dir", str(tmp_path / "absent")])
