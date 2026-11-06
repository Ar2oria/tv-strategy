"""Alembic repeatability and SQLite connection pragma tests."""

from pathlib import Path

from alembic import command
from sqlalchemy import inspect

from app.db.database import SessionFactory
from tests.conftest import migration_config


def test_upgrade_head_twice_and_sqlite_pragmas(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite3"
    config = migration_config(database_path)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    factory = SessionFactory(database_path)
    try:
        with factory.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert {
                "instruments",
                "universe_memberships",
                "daily_bars",
                "task_runs",
                "task_logs",
            }.issubset(inspect(connection).get_table_names())
    finally:
        factory.dispose()
