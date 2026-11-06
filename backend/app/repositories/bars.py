"""Parameterized daily bar reads and transactional SQLite upserts."""

from collections.abc import Iterable
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.database import SessionFactory
from app.db.types import utc_now
from app.domain.dto import BarDTO
from app.models.bar import DailyBar


def _values(instrument_id: int, bar: BarDTO) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "date": bar.time,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "source": bar.source,
        "adjustment": bar.adjustment,
        "updated_at": utc_now(),
    }


def _dto(bar: DailyBar) -> BarDTO:
    return BarDTO(
        time=bar.date,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        adjustment=bar.adjustment,
    )


def _upsert(
    session: Session, instrument_id: int, bars: tuple[BarDTO, ...]
) -> int:
    if not bars:
        return 0
    statement = sqlite_insert(DailyBar)
    statement = statement.on_conflict_do_update(
        index_elements=["instrument_id", "date"],
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
            "source": statement.excluded.source,
            "adjustment": statement.excluded.adjustment,
            "updated_at": statement.excluded.updated_at,
        },
    )
    session.execute(
        statement,
        [_values(instrument_id, bar) for bar in bars],
    )
    return len(bars)


class BarRepository:
    """Read and replace immutable DTO collections without mutating inputs."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def upsert(
        self, instrument_id: int, bars: Iterable[BarDTO] | BarDTO
    ) -> int:
        """Insert new dates and update all fields for existing dates."""
        items = (bars,) if isinstance(bars, BarDTO) else tuple(bars)
        with self._sessions() as session:
            with session.begin():
                return _upsert(session, instrument_id, items)

    def replace_all(
        self, instrument_id: int, bars: Iterable[BarDTO]
    ) -> int:
        """Replace one instrument's full series in a single transaction."""
        items = tuple(bars)
        with self._sessions() as session:
            with session.begin():
                session.execute(
                    delete(DailyBar).where(DailyBar.instrument_id == instrument_id)
                )
                return _upsert(session, instrument_id, items)

    def get_all_until(
        self, instrument_id: int, end: date | None
    ) -> list[BarDTO]:
        """Return stored history through end (None means unbounded)."""
        conditions = [DailyBar.instrument_id == instrument_id]
        if end is not None:
            conditions.append(DailyBar.date <= end)
        statement = (
            select(DailyBar)
            .where(*conditions)
            .order_by(DailyBar.date)
        )
        with self._sessions() as session:
            return [_dto(bar) for bar in session.scalars(statement).all()]

    def get_range(
        self, instrument_id: int, start: date, end: date
    ) -> list[BarDTO]:
        """Return an inclusive date range in ascending order."""
        if start > end:
            raise ValueError("start must not be later than end")
        statement = (
            select(DailyBar)
            .where(
                DailyBar.instrument_id == instrument_id,
                DailyBar.date >= start,
                DailyBar.date <= end,
            )
            .order_by(DailyBar.date)
        )
        with self._sessions() as session:
            return [_dto(bar) for bar in session.scalars(statement).all()]

    def latest_date(self, instrument_id: int) -> date | None:
        """Return the latest stored trading date for incremental sync."""
        statement = select(func.max(DailyBar.date)).where(
            DailyBar.instrument_id == instrument_id
        )
        with self._sessions() as session:
            return session.scalar(statement)
