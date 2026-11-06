"""Shared fixtures for file-backed backend database tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.db.database import SessionFactory

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migration_config(database_path: Path) -> Config:
    """Return Alembic configuration targeting one temporary database."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def upgrade_database(database_path: Path) -> None:
    """Apply the real migrations rather than creating tables from metadata."""
    command.upgrade(migration_config(database_path), "head")


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[SessionFactory]:
    database_path = tmp_path / "repository.sqlite3"
    upgrade_database(database_path)
    factory = SessionFactory(database_path)
    try:
        yield factory
    finally:
        factory.dispose()
