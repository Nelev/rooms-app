"""The app's own Postgres tables (the projects registry); the checkpointer and the store keep theirs."""

from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).parents[2] / "migrations" / "alembic.ini"


def migrate(dsn: str) -> None:
    """Create the tables, or bring them up to date (see migrations/). Blocking: run it at startup, before serving."""
    config = Config(ALEMBIC_INI)
    config.attributes["dsn"] = dsn
    command.upgrade(config, "head")
