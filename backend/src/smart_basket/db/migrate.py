"""Run Alembic migrations with the packaged scripts (`smart-basket-migrate [revision]`)."""

import sys
from importlib.resources import files

from alembic import command
from alembic.config import Config

from smart_basket.config import get_settings


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic configuration pointing at the migrations shipped inside the package."""
    cfg = Config()
    cfg.set_main_option("script_location", str(files("smart_basket.db") / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return cfg


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    action = args[0] if args else "upgrade"
    revision = args[1] if len(args) > 1 else ("head" if action == "upgrade" else "base")
    cfg = alembic_config()
    if action == "upgrade":
        command.upgrade(cfg, revision)
    elif action == "downgrade":
        command.downgrade(cfg, revision)
    elif action == "current":
        command.current(cfg, verbose=True)
    else:
        raise SystemExit(f"unknown action {action!r}: use upgrade, downgrade or current")


if __name__ == "__main__":
    main()
