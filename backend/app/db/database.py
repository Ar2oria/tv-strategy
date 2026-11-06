"""SQLite engine and short-lived SQLAlchemy session construction."""

import sqlite3
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

SQLITE_BUSY_TIMEOUT_MS = 5000


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(
    dbapi_connection: object, connection_record: object
) -> None:
    """Enable constraints and WAL on every SQLAlchemy SQLite connection."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def database_url(database: str | Path) -> str:
    """Normalize a filesystem path or URL and reject non-SQLite targets."""
    raw = str(database)
    url = raw if "://" in raw else f"sqlite:///{Path(raw).expanduser().resolve()}"
    if make_url(url).get_backend_name() != "sqlite":
        raise ValueError("SessionFactory supports SQLite databases only")
    return url


class SessionFactory:
    """Own an engine and create independent, short-lived sessions."""

    def __init__(self, database: str | Path, *, echo: bool = False) -> None:
        self.url = database_url(database)
        self.engine = create_engine(
            self.url,
            echo=echo,
            connect_args={"check_same_thread": False},
        )
        self._sessionmaker = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def __call__(self) -> Session:
        """Return a new session; callers control its context and transaction."""
        return self._sessionmaker()

    def session(self) -> Session:
        """Named equivalent of calling the factory."""
        return self()

    def dispose(self) -> None:
        """Release pooled SQLite connections."""
        self.engine.dispose()
