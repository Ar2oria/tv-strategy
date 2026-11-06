"""Alembic online/offline migration environment."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import database as _database  # noqa: F401  (registers pragmas)
from app.db.base import Base
from app.models import bar as _bar  # noqa: F401
from app.models import instrument as _instrument  # noqa: F401
from app.models import task_run as _task_run  # noqa: F401

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without creating a database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with SQLite connection listeners installed."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
