"""Final range, completeness, retry, and cooperative-timeout invariants."""

import asyncio
import threading
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.db.database import SessionFactory
from app.domain.dto import InstrumentRecord
from app.providers.errors import (
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.services.bar_sync_service import BarSyncService
from tests.market_sync_fixtures import TODAY, ScriptedProvider, bar, instrument_dto, market_config


@pytest.fixture
def bars(session_factory: SessionFactory) -> BarRepository:
    return BarRepository(session_factory)


@pytest.fixture
def instrument(session_factory: SessionFactory) -> InstrumentRecord:
    return InstrumentRepository(session_factory).upsert_catalog(instrument_dto())[0]


def sync_service(bars: BarRepository, delays: list[float] | None = None) -> BarSyncService:
    return BarSyncService(bars, today=lambda: TODAY)


@pytest.mark.parametrize("boundary", ["pre-start", "future"])
@pytest.mark.anyio
async def test_full_response_outside_requested_range_preserves_old_bars_without_retry(
    bars: BarRepository,
    instrument: InstrumentRecord,
    boundary: str,
) -> None:
    original = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, original)
    config = market_config()
    requested_start = date(2024, 1, 31)
    invalid = bar(
        requested_start - timedelta(days=1)
        if boundary == "pre-start"
        else TODAY + timedelta(days=1)
    )
    provider = ScriptedProvider([bar(requested_start), bar(TODAY), invalid])

    with pytest.raises(ProviderDataInvalid, match="range"):
        await sync_service(bars).sync_instrument(
            instrument, provider, config, full_refresh=True
        )

    assert len(provider.calls) == 1
    assert bars.get_all_until(instrument.id, TODAY + timedelta(days=2)) == [original]


@pytest.mark.parametrize("boundary", ["pre-start", "future"])
@pytest.mark.anyio
async def test_incremental_response_outside_overlap_range_is_rejected_before_write(
    bars: BarRepository,
    instrument: InstrumentRecord,
    boundary: str,
) -> None:
    original = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, original)
    requested_start = TODAY - timedelta(days=6)
    invalid = bar(
        requested_start - timedelta(days=1)
        if boundary == "pre-start"
        else TODAY + timedelta(days=1)
    )
    provider = ScriptedProvider([bar(TODAY), invalid])

    with pytest.raises(ProviderDataInvalid, match="range"):
        await sync_service(bars).sync_instrument(
            instrument, provider, market_config()
        )

    assert len(provider.calls) == 1
    assert bars.get_all_until(instrument.id, TODAY + timedelta(days=2)) == [original]


@pytest.mark.anyio
async def test_requested_start_and_end_are_inclusive(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    requested_start = date(2024, 1, 31)
    supplied = [bar(requested_start), bar(TODAY)]

    outcome = await sync_service(bars).sync_instrument(
        instrument,
        ScriptedProvider(supplied),
        market_config(),
    )

    assert outcome.bar_count == 2
    assert bars.get_all_until(instrument.id, TODAY) == supplied


@pytest.mark.anyio
async def test_full_history_starting_after_existing_requested_history_is_rejected(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = bar(date(2024, 2, 1))
    bars.upsert(instrument.id, original)
    provider = ScriptedProvider([bar(date(2025, 1, 1))])

    with pytest.raises(ProviderDataInvalid, match="starts after existing") as captured:
        await sync_service(bars).sync_instrument(
            instrument, provider, market_config(), full_refresh=True
        )

    assert "starts after existing" in (captured.value.detail or "")
    assert bars.get_all_until(instrument.id, TODAY) == [original]


@pytest.mark.anyio
async def test_full_history_missing_existing_newer_bars_is_rejected_without_delete(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = [bar(date(2024, 2, 1)), bar(date(2025, 1, 1))]
    bars.upsert(instrument.id, original)
    incomplete = [original[0], bar(date(2024, 6, 1))]

    with pytest.raises(ProviderDataInvalid, match="ends before existing"):
        await sync_service(bars).sync_instrument(
            instrument,
            ScriptedProvider(incomplete),
            market_config(),
            full_refresh=True,
        )

    assert bars.get_all_until(instrument.id, TODAY) == original


@pytest.mark.anyio
async def test_full_history_missing_interior_date_with_later_bar_preserves_all_bars(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = [
        bar(date(2024, 2, 1)),
        bar(date(2024, 3, 1)),
        bar(date(2025, 1, 1)),
    ]
    bars.upsert(instrument.id, original)
    incomplete = [original[0], original[2], bar(TODAY)]

    with pytest.raises(ProviderDataInvalid, match="missing existing dates"):
        await sync_service(bars).sync_instrument(
            instrument,
            ScriptedProvider(incomplete),
            market_config(),
            full_refresh=True,
        )

    assert bars.get_all_until(instrument.id, TODAY) == original


@pytest.mark.anyio
async def test_intentionally_shorter_range_does_not_reject_older_out_of_range_history(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    bars.upsert(instrument.id, bar(date(2024, 1, 1)))
    replacement = bar(date(2025, 1, 1))

    outcome = await sync_service(bars).sync_instrument(
        instrument,
        ScriptedProvider([replacement]),
        market_config(),
        full_refresh=True,
    )

    assert outcome.full_refresh is True
    assert bars.get_all_until(instrument.id, TODAY) == [replacement]


@pytest.mark.anyio
async def test_prelisting_full_history_can_start_after_requested_start(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    listed = date(2025, 1, 1)

    outcome = await sync_service(bars).sync_instrument(
        instrument, ScriptedProvider([bar(listed)]), market_config()
    )

    assert outcome.bar_count == 1
    assert bars.get_all_until(instrument.id, TODAY) == [bar(listed)]


@pytest.mark.anyio
async def test_adjustment_triggered_second_full_fetch_must_also_be_complete(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    old = bar(date(2024, 2, 1))
    latest = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, [old, latest])
    changed = replace(latest, close=20.0, high=21.0)
    provider = ScriptedProvider([changed], [bar(date(2025, 1, 1))])

    with pytest.raises(ProviderDataInvalid, match="starts after existing"):
        await sync_service(bars).sync_instrument(
            instrument, provider, market_config()
        )

    assert len(provider.calls) == 2
    assert bars.get_all_until(instrument.id, TODAY) == [old, latest]


@pytest.mark.anyio
async def test_retry_after_guidance_does_not_trigger_a_second_request(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    delays: list[float] = []
    limited = ProviderRateLimited(retry_after=45.0)
    provider = ScriptedProvider(limited)

    with pytest.raises(ProviderRateLimited):
        await sync_service(bars, delays).sync_instrument(
            instrument, provider, market_config()
        )

    assert len(provider.calls) == 1
    assert delays == []


@pytest.mark.anyio
async def test_cooperative_timeout_never_writes_late_worker_result(
    bars: BarRepository,
    instrument: InstrumentRecord,
) -> None:
    original = bar(TODAY - timedelta(days=1))
    bars.upsert(instrument.id, original)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingProvider:
        def fetch_daily(self, *args: object) -> list[object]:
            started.set()
            release.wait(2.0)
            finished.set()
            return [bar(TODAY)]

    task = asyncio.create_task(
        sync_service(bars).sync_instrument(
            instrument,
            BlockingProvider(),  # type: ignore[arg-type]
            market_config(request_timeout_seconds=0.01),
            full_refresh=True,
        )
    )
    assert await asyncio.to_thread(started.wait, 1.0)
    try:
        with pytest.raises(ProviderUnavailable) as captured:
            await task
        assert "cooperative" in (captured.value.detail or "").casefold()
    finally:
        release.set()
    assert await asyncio.to_thread(finished.wait, 1.0)
    await asyncio.sleep(0)
    assert bars.get_all_until(instrument.id, TODAY) == [original]
