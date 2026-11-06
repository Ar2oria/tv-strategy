"""Daily bar uniqueness, upsert, replacement, and range tests."""

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.db.database import SessionFactory
from app.domain.dto import BarDTO, InstrumentDTO
from app.models.bar import DailyBar
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository


def instrument(symbol: str = "AAA") -> InstrumentDTO:
    return InstrumentDTO(
        symbol=symbol,
        name=symbol,
        market="us_stock",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        instrument_type="stock",
        provider_symbol=symbol,
    )


def bar(day: date, *, close: float = 11.0, source: str = "fixture") -> BarDTO:
    return BarDTO(
        time=day,
        open=10.0,
        high=12.0,
        low=9.0,
        close=close,
        volume=1000.0,
        source=source,
        adjustment="qfq",
    )


@pytest.fixture
def instrument_id(session_factory: SessionFactory) -> int:
    return InstrumentRepository(session_factory).upsert_catalog(
        [instrument()]
    )[0].id


def test_upsert_updates_without_duplication_and_database_rejects_duplicate(
    session_factory: SessionFactory,
    instrument_id: int,
) -> None:
    repository = BarRepository(session_factory)
    original = bar(date(2025, 1, 2))
    assert repository.upsert(instrument_id, original) == 1

    updated = replace(original, close=13.5, source="replacement")
    assert repository.upsert(instrument_id, [updated]) == 1
    assert repository.get_range(
        instrument_id, date(2025, 1, 1), date(2025, 1, 3)
    ) == [updated]

    duplicate = {
        "instrument_id": instrument_id,
        "date": original.time,
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 1000.0,
        "source": "raw",
        "adjustment": "qfq",
    }
    with session_factory() as session:
        with pytest.raises(IntegrityError):
            session.execute(insert(DailyBar), duplicate)
            session.flush()
        session.rollback()


def test_history_is_ascending_and_ranges_are_inclusive(
    session_factory: SessionFactory,
    instrument_id: int,
) -> None:
    repository = BarRepository(session_factory)
    dates = [date(2025, 1, day) for day in (4, 1, 3, 2)]
    repository.upsert(instrument_id, [bar(day) for day in dates])

    assert repository.get_all_until(instrument_id, date(2025, 1, 3)) == [
        bar(date(2025, 1, day)) for day in (1, 2, 3)
    ]
    assert repository.get_range(
        instrument_id, date(2025, 1, 2), date(2025, 1, 4)
    ) == [bar(date(2025, 1, day)) for day in (2, 3, 4)]
    assert repository.latest_date(instrument_id) == date(2025, 1, 4)


def test_replace_all_removes_only_stale_dates_for_target_instrument(
    session_factory: SessionFactory,
    instrument_id: int,
) -> None:
    instruments = InstrumentRepository(session_factory)
    other_id = instruments.upsert_catalog([instrument("BBB")])[0].id
    repository = BarRepository(session_factory)
    repository.upsert(
        instrument_id,
        [bar(date(2025, 1, 1)), bar(date(2025, 1, 2))],
    )
    other_bar = bar(date(2025, 1, 1), close=20.0)
    repository.upsert(other_id, other_bar)
    replacement = (
        bar(date(2025, 1, 2), close=15.0),
        bar(date(2025, 1, 3)),
    )

    assert repository.replace_all(instrument_id, replacement) == 2

    assert replacement[0].close == 15.0
    assert repository.get_all_until(instrument_id, date(2025, 1, 4)) == list(
        replacement
    )
    assert repository.get_all_until(other_id, date(2025, 1, 4)) == [other_bar]
