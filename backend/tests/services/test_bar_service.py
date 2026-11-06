"""Daily-history reads and immutable weekly/monthly aggregation tests."""

from datetime import date

import pytest

from app.db.database import SessionFactory
from app.domain.dto import BarDTO, InstrumentDTO, Timeframe
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.services.bar_service import BarService, InstrumentNotFoundError, aggregate_daily


def make_bar(
    day: date,
    *,
    open_: float = 10.0,
    high: float = 12.0,
    low: float = 9.0,
    close: float = 11.0,
    volume: float | None = 100.0,
    source: str = "fixture",
) -> BarDTO:
    return BarDTO(
        time=day,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=source,
        adjustment="qfq",
    )


def make_service(factory: SessionFactory) -> BarService:
    return BarService(BarRepository(factory), InstrumentRepository(factory))


@pytest.fixture
def instrument_id(session_factory: SessionFactory) -> int:
    instrument = InstrumentDTO(
        symbol="AAA",
        name="Alpha",
        market="us_stock",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        instrument_type="stock",
        provider_symbol="AAA",
    )
    return InstrumentRepository(session_factory).upsert_catalog(instrument)[0].id


def test_weekly_aggregation_uses_ohlcv_and_actual_last_trading_date() -> None:
    bars = (
        make_bar(date(2026, 1, 5), open_=10.0, high=13.0, close=12.0),
        make_bar(
            date(2026, 1, 6),
            open_=12.0,
            high=15.0,
            low=11.0,
            close=14.0,
            volume=None,
            source="middle",
        ),
        # Friday 2026-01-09 is absent: Thursday must label this week.
        make_bar(
            date(2026, 1, 8),
            open_=14.0,
            high=16.0,
            low=13.0,
            close=15.0,
            volume=50.0,
            source="last",
        ),
        make_bar(date(2026, 1, 12), close=20.0),
    )

    weekly = aggregate_daily(bars, "1w")

    assert weekly == [
        make_bar(
            date(2026, 1, 8),
            open_=10.0,
            high=16.0,
            low=9.0,
            close=15.0,
            volume=None,
            source="last",
        ),
        make_bar(date(2026, 1, 12), close=20.0),
    ]
    assert bars[0].close == 12.0


def test_monthly_aggregation_keeps_all_null_volume_null() -> None:
    bars = (
        make_bar(date(2026, 1, 29), volume=None, close=10.0),
        make_bar(
            date(2026, 1, 30),
            open_=11.0,
            high=14.0,
            low=8.0,
            close=13.0,
            volume=None,
            source="january-last",
        ),
        make_bar(date(2026, 2, 2), volume=0.0),
        make_bar(date(2026, 2, 3), volume=25.0, source="february-last"),
    )

    monthly = aggregate_daily(bars, "1M")

    assert [bar.time for bar in monthly] == [date(2026, 1, 30), date(2026, 2, 3)]
    assert monthly[0].volume is None
    assert monthly[0].open == 10.0
    assert monthly[0].high == 14.0
    assert monthly[0].low == 8.0
    assert monthly[0].close == 13.0
    assert monthly[0].source == "january-last"
    assert monthly[1].volume == 25.0


def test_monthly_aggregation_discards_a_partially_known_volume_sum() -> None:
    bars = (
        make_bar(date(2026, 3, 30), volume=100.0),
        make_bar(date(2026, 3, 31), volume=None),
        make_bar(date(2026, 4, 1), volume=0.0),
    )

    monthly = aggregate_daily(bars, "1M")

    assert monthly[0].volume is None
    assert monthly[1].volume == 0.0


def test_iso_week_groups_calendar_year_boundary_correctly() -> None:
    bars = (
        make_bar(date(2025, 12, 29), open_=7.0, close=8.0),
        make_bar(date(2026, 1, 1), close=9.0, source="new-year"),
        make_bar(date(2026, 1, 5), close=10.0),
    )

    weekly = aggregate_daily(bars, "1w")

    assert len(weekly) == 2
    assert weekly[0].time == date(2026, 1, 1)
    assert weekly[0].open == 7.0
    assert weekly[0].close == 9.0


@pytest.mark.parametrize("timeframe", ["1d", "1w", "1M"])
def test_visible_reads_trim_after_aggregation(
    session_factory: SessionFactory,
    instrument_id: int,
    timeframe: Timeframe,
) -> None:
    bars = [
        make_bar(date(2025, 12, 30), open_=5.0, close=6.0),
        make_bar(date(2025, 12, 31), close=7.0),
        make_bar(date(2026, 1, 2), close=8.0, source="visible-last"),
        make_bar(date(2026, 1, 5), close=9.0),
    ]
    repository = BarRepository(session_factory)
    repository.upsert(instrument_id, bars)

    visible = make_service(session_factory).get_visible(
        instrument_id,
        timeframe,
        date(2026, 1, 1),
        date(2026, 1, 4),
    )

    assert len(visible) == 1
    assert visible[0].time == date(2026, 1, 2)
    assert visible[0].close == 8.0
    if timeframe == "1w":
        assert visible[0].open == 5.0
    else:
        assert visible[0].open == 10.0
    assert len(repository.get_all_until(instrument_id, date(2026, 1, 6))) == 4


def test_history_until_aggregates_once_and_visible_limit_returns_latest(
    session_factory: SessionFactory,
    instrument_id: int,
) -> None:
    repository = BarRepository(session_factory)
    bars = [make_bar(date(2026, 1, day), close=float(day)) for day in range(1, 6)]
    repository.upsert(instrument_id, bars)
    service = make_service(session_factory)

    history = service.get_history_until(instrument_id, date(2026, 1, 4), "1M")
    visible = service.get_visible(
        instrument_id,
        "1d",
        date(2026, 1, 1),
        date(2026, 1, 5),
        limit=2,
    )

    assert history == [
        make_bar(date(2026, 1, 4), open_=10.0, close=4.0, volume=400.0)
    ]
    assert [bar.time for bar in visible] == [date(2026, 1, 4), date(2026, 1, 5)]


def test_missing_instrument_and_invalid_ranges_fail_explicitly(
    session_factory: SessionFactory,
) -> None:
    service = make_service(session_factory)

    with pytest.raises(InstrumentNotFoundError):
        service.get_history_until(999, date(2026, 1, 1))
    with pytest.raises(InstrumentNotFoundError):
        service.get_visible(999, "1d", date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(ValueError, match="timeframe"):
        aggregate_daily((), "2d")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="strictly increasing"):
        aggregate_daily(
            (make_bar(date(2026, 1, 2)), make_bar(date(2026, 1, 1))),
            "1d",
        )
