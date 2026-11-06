"""Explicitly opted-in public-provider smoke tests with isolated persistence.

Only standard-library modules and pytest are imported during default collection.
Provider SDK imports and all network access stay inside tests skipped unless the
operator sets STOCK_LAB_ONLINE=1.
"""

import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from app.db.database import SessionFactory
    from app.domain.dto import BarDTO, InstrumentDTO, UniverseSnapshot
    from app.providers.base import OhlcvProvider, UniverseProvider

ONLINE_ENVIRONMENT_VARIABLE = "STOCK_LAB_ONLINE"
ONLINE_OPT_IN_VALUE = "1"
SMOKE_RANGE_DAYS = 14
LAST_COMPLETE_DAY_OFFSET = 1

pytestmark = [
    pytest.mark.online,
    pytest.mark.skipif(
        os.environ.get(ONLINE_ENVIRONMENT_VARIABLE) != ONLINE_OPT_IN_VALUE,
        reason=f"public-provider smoke tests require {ONLINE_ENVIRONMENT_VARIABLE}=1",
    ),
]


@dataclass(frozen=True, slots=True)
class OhlcvSmokeCase:
    market: str
    provider_name: str
    symbol: str
    name: str
    exchange: str
    currency: str
    timezone: str
    provider_symbol: str
    adjustment: str
    instrument_type: str = "stock"

    def instrument(self) -> "InstrumentDTO":
        from app.domain.dto import InstrumentDTO

        return InstrumentDTO(
            symbol=self.symbol,
            name=self.name,
            market=self.market,  # type: ignore[arg-type]
            exchange=self.exchange,
            currency=self.currency,
            timezone=self.timezone,
            instrument_type=self.instrument_type,  # type: ignore[arg-type]
            provider_symbol=self.provider_symbol,
        )


@dataclass(frozen=True, slots=True)
class UniverseSmokeCase:
    code: str
    market: str
    provider_name: str


OHLCV_CASES = (
    OhlcvSmokeCase(
        market="a_share",
        provider_name="akshare",
        symbol="600519.SH",
        name="Kweichow Moutai",
        exchange="SSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        provider_symbol="600519",
        adjustment="qfq",
    ),
    OhlcvSmokeCase(
        market="hk_stock",
        provider_name="akshare",
        symbol="00700.HK",
        name="Tencent Holdings",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        provider_symbol="00700",
        adjustment="qfq",
    ),
    OhlcvSmokeCase(
        market="hk_stock",
        provider_name="yfinance",
        symbol="0700.HK",
        name="Tencent Holdings",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        provider_symbol="0700.HK",
        adjustment="qfq",
    ),
    OhlcvSmokeCase(
        market="us_stock",
        provider_name="yfinance",
        symbol="AAPL",
        name="Apple Inc.",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        provider_symbol="AAPL",
        adjustment="qfq",
    ),
    OhlcvSmokeCase(
        market="crypto",
        provider_name="binance",
        symbol="BINANCE:BTC/USDT",
        name="BTC/USDT Binance Spot",
        exchange="binance",
        currency="USDT",
        timezone="UTC",
        provider_symbol="BTC/USDT",
        adjustment="none",
        instrument_type="crypto_spot",
    ),
    OhlcvSmokeCase(
        market="crypto",
        provider_name="okx",
        symbol="OKX:BTC/USDT",
        name="BTC/USDT OKX Spot",
        exchange="okx",
        currency="USDT",
        timezone="UTC",
        provider_symbol="BTC/USDT",
        adjustment="none",
        instrument_type="crypto_spot",
    ),
)

UNIVERSE_CASES = (
    UniverseSmokeCase("csi300", "a_share", "akshare"),
    UniverseSmokeCase("star_market", "a_share", "akshare"),
    UniverseSmokeCase("chinext", "a_share", "akshare"),
    UniverseSmokeCase("hstech", "hk_stock", "hstech"),
    UniverseSmokeCase("nasdaq100", "us_stock", "invesco"),
    UniverseSmokeCase("soxx", "us_stock", "ishares"),
)


@contextmanager
def temporary_sessions(tmp_path: Path) -> Iterator["SessionFactory"]:
    """Migrate and dispose one per-test database, never the configured database."""
    from app.db.database import SessionFactory
    from tests.conftest import upgrade_database

    database_path = tmp_path / "online-market-smoke.sqlite3"
    upgrade_database(database_path)
    sessions = SessionFactory(database_path)
    try:
        yield sessions
    finally:
        sessions.dispose()


def bounded_range() -> tuple[date, date]:
    """Keep CCXT responses small by requesting only recent complete UTC days."""
    end = datetime.now(UTC).date() - timedelta(days=LAST_COMPLETE_DAY_OFFSET)
    return end - timedelta(days=SMOKE_RANGE_DAYS - 1), end


def ohlcv_provider(case: OhlcvSmokeCase) -> "OhlcvProvider":
    if case.provider_name == "akshare":
        from app.providers.akshare_ohlcv import AkshareOhlcvProvider

        return AkshareOhlcvProvider()
    if case.provider_name == "yfinance":
        from app.providers.yahoo_ohlcv import YahooOhlcvProvider

        return YahooOhlcvProvider()
    if case.provider_name in {"binance", "okx"}:
        from app.providers.ccxt_ohlcv import CcxtOhlcvProvider

        return CcxtOhlcvProvider(case.provider_name)  # type: ignore[arg-type]
    raise AssertionError(f"Unmapped OHLCV smoke provider: {case.provider_name}")


def universe_provider(case: UniverseSmokeCase) -> "UniverseProvider":
    if case.provider_name == "akshare":
        from app.providers.a_share_universes import AkshareUniverseProvider

        return AkshareUniverseProvider()
    if case.provider_name == "hstech":
        from app.providers.hstech_universe import HstechUniverseProvider

        return HstechUniverseProvider()
    if case.provider_name == "invesco":
        from app.providers.invesco_universe import InvescoUniverseProvider

        return InvescoUniverseProvider()
    if case.provider_name == "ishares":
        from app.providers.ishares_soxx import IsharesSoxxUniverseProvider

        return IsharesSoxxUniverseProvider()
    raise AssertionError(f"Unmapped universe smoke provider: {case.provider_name}")


def assert_bar_structure(
    rows: object,
    case: OhlcvSmokeCase,
    start: date,
    end: date,
) -> list["BarDTO"]:
    from app.domain.dto import BarDTO

    assert isinstance(rows, list), "Provider must return a list of normalized bars"
    assert rows, f"No {case.market} bars returned for {start} through {end}"
    assert len(rows) <= (end - start).days + 1
    for row in rows:
        assert isinstance(row, BarDTO)
        assert type(row.time) is date
        assert start <= row.time <= end
        assert row.source == case.provider_name
        assert row.adjustment == case.adjustment
        assert all(
            math.isfinite(value) and value > 0
            for value in (row.open, row.high, row.low, row.close)
        )
        assert row.low <= row.open <= row.high
        assert row.low <= row.close <= row.high
        assert row.volume is not None
        assert math.isfinite(row.volume) and row.volume >= 0
    dates = [row.time for row in rows]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)
    return rows


def assert_universe_structure(
    snapshot: object,
    case: UniverseSmokeCase,
) -> "UniverseSnapshot":
    from app.domain.dto import InstrumentDTO, UniverseSnapshot

    assert isinstance(snapshot, UniverseSnapshot)
    assert snapshot.universe_code == case.code
    assert isinstance(snapshot.source, str) and snapshot.source.strip()
    assert snapshot.effective_date is None or type(snapshot.effective_date) is date
    assert snapshot.members, "A current universe snapshot must contain members"
    member_keys: set[tuple[str, str]] = set()
    for member in snapshot.members:
        assert_instrument_structure(member, InstrumentDTO)
        assert member.market == case.market
        assert member.instrument_type == "stock"
        key = (member.market, member.symbol)
        assert key not in member_keys, f"Duplicate universe member: {key}"
        member_keys.add(key)
    for related in snapshot.related_instruments:
        assert_instrument_structure(related, InstrumentDTO)
    return snapshot


def assert_instrument_structure(
    instrument: object,
    expected_type: type["InstrumentDTO"],
) -> None:
    assert isinstance(instrument, expected_type)
    for value in (
        instrument.symbol,
        instrument.name,
        instrument.market,
        instrument.exchange,
        instrument.currency,
        instrument.timezone,
        instrument.instrument_type,
        instrument.provider_symbol,
    ):
        assert isinstance(value, str) and value.strip()


def seed_bar(case: OhlcvSmokeCase, start: date) -> "BarDTO":
    from app.domain.dto import BarDTO

    return BarDTO(
        time=start - timedelta(days=1),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
        source=case.provider_name,
        adjustment=case.adjustment,  # type: ignore[arg-type]
    )


def seed_universe(case: UniverseSmokeCase) -> "UniverseSnapshot":
    from app.domain.dto import InstrumentDTO, UniverseSnapshot

    old_member = InstrumentDTO(
        symbol="ONLINE.SMOKE.OLD",
        name="Temporary smoke sentinel",
        market=case.market,  # type: ignore[arg-type]
        exchange="SMOKE",
        currency="USD",
        timezone="UTC",
        instrument_type="stock",
        provider_symbol="ONLINE.SMOKE.OLD",
    )
    return UniverseSnapshot(
        universe_code=case.code,
        source="online_smoke_sentinel",
        effective_date=None,
        members=(old_member,),
    )


def raise_sanitized(error: Exception) -> None:
    """Preserve precise schema messages while dropping sensitive upstream causes."""
    from app.providers.errors import ProviderError

    if isinstance(error, ProviderError):
        raise type(error)(str(error)) from None
    raise error


@pytest.mark.parametrize(
    "case",
    OHLCV_CASES,
    ids=lambda case: f"{case.market}-{case.provider_name}",
)
def test_bounded_daily_sample_and_temporary_persistence(
    case: OhlcvSmokeCase,
    tmp_path: Path,
) -> None:
    from app.repositories.bars import BarRepository
    from app.repositories.instruments import InstrumentRepository

    start, end = bounded_range()
    with temporary_sessions(tmp_path) as sessions:
        instruments = InstrumentRepository(sessions)
        record = instruments.upsert_catalog(case.instrument())[0]
        bars = BarRepository(sessions)
        sentinel = seed_bar(case, start)
        bars.replace_all(record.id, [sentinel])
        try:
            rows = ohlcv_provider(case).fetch_daily(
                case.instrument(), start, end, case.adjustment  # type: ignore[arg-type]
            )
            validated = assert_bar_structure(rows, case, start, end)
        except Exception as error:
            assert bars.get_all_until(record.id, end) == [sentinel]
            raise_sanitized(error)

        bars.replace_all(record.id, validated)
        assert bars.get_all_until(record.id, end) == validated

    print(
        f"{case.market}/{case.provider_name}: {len(validated)} bars, "
        f"inclusive range {start} through {end}; temporary persistence passed"
    )


@pytest.mark.parametrize("case", UNIVERSE_CASES, ids=lambda case: case.code)
def test_current_universe_structure_and_temporary_persistence(
    case: UniverseSmokeCase,
    tmp_path: Path,
) -> None:
    from app.repositories.instruments import InstrumentRepository

    with temporary_sessions(tmp_path) as sessions:
        instruments = InstrumentRepository(sessions)
        sentinel = seed_universe(case)
        instruments.replace_universe(sentinel)
        try:
            snapshot = universe_provider(case).fetch_universe(case.code)
            validated = assert_universe_structure(snapshot, case)
        except Exception as error:
            assert [item.symbol for item in instruments.list_members(case.code)] == [
                "ONLINE.SMOKE.OLD"
            ]
            raise_sanitized(error)

        instrument_count, member_count = instruments.replace_universe(validated)
        stored_members = instruments.list_members(case.code)
        assert member_count == len(validated.members)
        assert instrument_count >= member_count
        assert len(stored_members) == len(validated.members)
        assert {(item.market, item.symbol) for item in stored_members} == {
            (item.market, item.symbol) for item in validated.members
        }

    print(
        f"{case.code}/{case.provider_name}: snapshot structure and "
        "temporary persistence passed"
    )
