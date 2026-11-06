"""Atomic, resumable daily-bar synchronization tests using offline providers."""

import asyncio
import threading
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.db.database import SessionFactory
from app.domain.dto import InstrumentRecord
from app.providers.errors import (
    NoDataAvailable,
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.services.bar_sync_service import (
    OHLC_ABSOLUTE_TOLERANCE,
    OHLC_RELATIVE_TOLERANCE,
    BarSyncService,
)
from tests.market_sync_fixtures import (
    TODAY,
    ScriptedProvider,
    bar,
    instrument_dto,
    market_config,
)


@pytest.fixture
def bars(session_factory: SessionFactory) -> BarRepository:
    return BarRepository(session_factory)


@pytest.fixture
def instrument(session_factory: SessionFactory) -> InstrumentRecord:
    return InstrumentRepository(session_factory).upsert_catalog(instrument_dto())[0]


def service(
    bars: BarRepository,
    *,
    delays: list[float] | None = None,
) -> BarSyncService:
    async def record_delay(delay: float) -> None:
        if delays is not None:
            delays.append(delay)

    return BarSyncService(
        bars,
        today=lambda: TODAY,
        sleep=record_delay,
    )


@pytest.mark.anyio
async def test_initial_full_load_uses_worker_thread_and_configured_history(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    calling_threads: list[int] = []

    class ThreadProvider(ScriptedProvider):
        def fetch_daily(self, *args: object) -> list[object]:
            calling_threads.append(threading.get_ident())
            return super().fetch_daily(*args)  # type: ignore[arg-type,return-value]

    supplied = [bar(TODAY), bar(TODAY - timedelta(days=1))]
    provider = ThreadProvider(supplied)

    outcome = await service(bars).sync_instrument(instrument, provider, market_config())

    assert calling_threads != [threading.get_ident()]
    assert provider.calls[0].start == date(2024, 1, 31)
    assert provider.calls[0].end == TODAY
    assert provider.calls[0].adjustment == "qfq"
    assert outcome.instrument_id == instrument.id
    assert outcome.status == "success"
    assert outcome.bar_count == 2
    assert outcome.full_refresh is True
    assert bars.get_all_until(instrument.id, TODAY) == list(reversed(supplied))


@pytest.mark.anyio
async def test_initial_empty_response_raises_without_replacing(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    provider = ScriptedProvider([])

    with pytest.raises(NoDataAvailable):
        await service(bars).sync_instrument(instrument, provider, market_config())

    assert bars.get_all_until(instrument.id, TODAY) == []


@pytest.mark.anyio
async def test_incremental_empty_response_is_successful_no_op(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, original)
    provider = ScriptedProvider([])

    outcome = await service(bars).sync_instrument(instrument, provider, market_config())

    assert outcome.bar_count == 0
    assert outcome.full_refresh is False
    assert outcome.status == "success"
    assert provider.calls[0].start == TODAY - timedelta(days=6)
    assert bars.get_all_until(instrument.id, TODAY) == [original]


@pytest.mark.anyio
async def test_incremental_upserts_overlap_without_full_refetch(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    latest = TODAY - timedelta(days=1)
    original = bar(latest)
    bars.upsert(instrument.id, original)
    overlap = replace(original, volume=999_999.0)
    new_bar = bar(TODAY, close=11.5)
    provider = ScriptedProvider([new_bar, overlap])

    outcome = await service(bars).sync_instrument(instrument, provider, market_config())

    assert len(provider.calls) == 1
    assert outcome.full_refresh is False
    assert outcome.bar_count == 2
    assert bars.get_all_until(instrument.id, TODAY) == [overlap, new_bar]


@pytest.mark.anyio
async def test_manual_full_refresh_replaces_complete_series(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    stale = bar(date(2020, 1, 1))
    bars.upsert(instrument.id, stale)
    replacement = [bar(TODAY - timedelta(days=1)), bar(TODAY)]
    provider = ScriptedProvider(replacement)

    outcome = await service(bars).sync_instrument(
        instrument, provider, market_config(), full_refresh=True
    )

    assert outcome.full_refresh is True
    assert outcome.bar_count == 2
    assert provider.calls[0].start == date(2024, 1, 31)
    assert bars.get_all_until(instrument.id, TODAY) == replacement


@pytest.mark.anyio
async def test_empty_full_refresh_preserves_old_series_byte_for_byte(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = [bar(TODAY - timedelta(days=1)), bar(TODAY)]
    bars.upsert(instrument.id, original)
    provider = ScriptedProvider([])

    with pytest.raises(NoDataAvailable):
        await service(bars).sync_instrument(
            instrument, provider, market_config(), full_refresh=True
        )

    assert bars.get_all_until(instrument.id, TODAY) == original


@pytest.mark.anyio
async def test_source_change_requires_one_full_non_empty_replacement(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = bar(TODAY - timedelta(days=1), source="akshare")
    bars.upsert(instrument.id, original)
    replacement = [bar(TODAY - timedelta(days=1)), bar(TODAY)]
    provider = ScriptedProvider(replacement)

    outcome = await service(bars).sync_instrument(instrument, provider, market_config())

    assert len(provider.calls) == 1
    assert provider.calls[0].start == date(2024, 1, 31)
    assert outcome.full_refresh is True
    assert bars.get_all_until(instrument.id, TODAY) == replacement


@pytest.mark.anyio
async def test_overlap_ohlc_change_triggers_second_full_fetch_and_replace(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    latest = TODAY - timedelta(days=1)
    original = bar(latest)
    bars.upsert(instrument.id, original)
    changed = replace(original, close=original.close * (1 + 2e-6))
    full_replacement = [changed, bar(TODAY)]
    provider = ScriptedProvider([changed], full_replacement)

    outcome = await service(bars).sync_instrument(instrument, provider, market_config())

    assert len(provider.calls) == 2
    assert provider.calls[0].start == latest - timedelta(days=5)
    assert provider.calls[1].start == date(2024, 1, 31)
    assert outcome.full_refresh is True
    assert bars.get_all_until(instrument.id, TODAY) == full_replacement


@pytest.mark.anyio
async def test_overlap_within_exact_tolerances_does_not_trigger_full_fetch(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    latest = TODAY - timedelta(days=1)
    original = bar(latest)
    bars.upsert(instrument.id, original)
    close = original.close + min(
        OHLC_ABSOLUTE_TOLERANCE / 2,
        original.close * OHLC_RELATIVE_TOLERANCE / 2,
    )
    changed = replace(original, close=close, high=max(original.high, close))
    provider = ScriptedProvider([changed])

    outcome = await service(bars).sync_instrument(instrument, provider, market_config())

    assert len(provider.calls) == 1
    assert outcome.full_refresh is False
    assert bars.get_all_until(instrument.id, TODAY) == [changed]


@pytest.mark.anyio
@pytest.mark.parametrize("second_response", [[], ProviderUnavailable("private url")])
async def test_failed_or_empty_second_full_fetch_preserves_old_bars(
    bars: BarRepository,
    instrument: InstrumentRecord,
    second_response: object,
) -> None:
    latest = TODAY - timedelta(days=1)
    original = bar(latest)
    bars.upsert(instrument.id, original)
    changed = replace(original, close=20.0, high=21.0)
    provider = ScriptedProvider([changed], second_response)

    with pytest.raises((NoDataAvailable, ProviderUnavailable)):
        await service(bars).sync_instrument(instrument, provider, market_config())

    assert bars.get_all_until(instrument.id, TODAY) == [original]


@pytest.mark.anyio
async def test_malformed_full_response_preserves_old_bars_without_retry(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, original)
    malformed = bar(TODAY, high=1.0)
    provider = ScriptedProvider([malformed])

    with pytest.raises(ProviderDataInvalid):
        await service(bars).sync_instrument(
            instrument, provider, market_config(max_retries=3), full_refresh=True
        )

    assert len(provider.calls) == 1
    assert bars.get_all_until(instrument.id, TODAY) == [original]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "metadata",
    [{"source": "akshare"}, {"adjustment": "none"}],
)
async def test_full_response_with_wrong_source_metadata_preserves_old_bars(
    bars: BarRepository,
    instrument: InstrumentRecord,
    metadata: dict[str, str],
) -> None:
    original = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, original)
    provider = ScriptedProvider([bar(TODAY, **metadata)])  # type: ignore[arg-type]

    with pytest.raises(ProviderDataInvalid, match="source or adjustment"):
        await service(bars).sync_instrument(
            instrument, provider, market_config(max_retries=3), full_refresh=True
        )

    assert len(provider.calls) == 1
    assert bars.get_all_until(instrument.id, TODAY) == [original]


@pytest.mark.anyio
async def test_retryable_failures_use_bounded_retries_and_upstream_delay(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    delays: list[float] = []
    limited = ProviderRateLimited("secret response")
    limited.retry_after = 2.5
    provider = ScriptedProvider(
        ProviderUnavailable(),
        limited,
        [bar(TODAY)],
    )

    outcome = await service(bars, delays=delays).sync_instrument(
        instrument, provider, market_config(max_retries=2)
    )

    assert outcome.bar_count == 1
    assert len(provider.calls) == 3
    assert delays == [1.0, 2.5]


@pytest.mark.anyio
async def test_retry_exhaustion_and_provider_failure_never_write_partial_data(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, original)
    delays: list[float] = []
    provider = ScriptedProvider(ProviderUnavailable(), ProviderUnavailable())

    with pytest.raises(ProviderUnavailable):
        await service(bars, delays=delays).sync_instrument(
            instrument, provider, market_config(max_retries=1)
        )

    assert len(provider.calls) == 2
    assert delays == [1.0]
    assert bars.get_all_until(instrument.id, TODAY) == [original]


@pytest.mark.anyio
async def test_crypto_history_none_passes_earliest_and_uses_no_adjustment(
    session_factory: SessionFactory,
    bars: BarRepository,
) -> None:
    instrument = InstrumentRepository(session_factory).upsert_catalog(
        instrument_dto(
            "BINANCE:BTC/USDT",
            market="crypto",
            instrument_type="crypto_spot",
            exchange="binance",
        )
    )[0]
    provider = ScriptedProvider([bar(TODAY, source="binance", adjustment="none")])

    await service(bars).sync_instrument(
        instrument,
        provider,
        market_config(provider="binance", history_years=None),
    )

    assert provider.calls[0].start is None
    assert provider.calls[0].adjustment == "none"


def test_sync_entry_point_is_async() -> None:
    assert asyncio.iscoroutinefunction(BarSyncService.sync_instrument)
