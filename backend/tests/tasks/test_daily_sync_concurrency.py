"""Bounded per-Task concurrency for daily market synchronization."""

import asyncio

import pytest

from app.config.defaults import default_settings
from app.db.database import SessionFactory
from app.domain.dto import InstrumentRecord
from app.providers.errors import ProviderRateLimited
from app.providers.registry import ProviderRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.repositories.task_runs import TaskRunRepository
from app.services.bar_sync_service import BarSyncOptions, SyncOutcome
from app.services.resources import RuntimeResources
from app.tasks.base import TaskContext
from app.tasks.builtin.sync_daily import DailySyncParams, USStockDailySyncTask
from tests.market_sync_fixtures import instrument_dto


class ControlledSync:
    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays
        self.active = 0
        self.max_active = 0
        self.calls: list[tuple[InstrumentRecord, BarSyncOptions, bool]] = []

    async def sync_instrument(
        self,
        instrument: InstrumentRecord,
        _provider: object,
        config: BarSyncOptions,
        full_refresh: bool = False,
    ) -> SyncOutcome:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append((instrument, config, full_refresh))
        try:
            await asyncio.sleep(self.delays.get(instrument.symbol, 0.0))
            if instrument.symbol in self.delays and self.delays[instrument.symbol] < 0:
                raise ProviderRateLimited(retry_after=30.0)
            return SyncOutcome(
                instrument_id=instrument.id,
                status="success",
                bar_count=1,
                full_refresh=full_refresh,
            )
        finally:
            self.active -= 1


class BlockingSync(ControlledSync):
    def __init__(self, immediate_symbols: frozenset[str] = frozenset()) -> None:
        super().__init__({})
        self.immediate_symbols = immediate_symbols
        self.release = asyncio.Event()
        self.complete_immediate = asyncio.Event()
        self.started = asyncio.Event()
        self.quiet = asyncio.Event()

    async def sync_instrument(
        self,
        instrument: InstrumentRecord,
        _provider: object,
        config: BarSyncOptions,
        full_refresh: bool = False,
    ) -> SyncOutcome:
        self.quiet.clear()
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append((instrument, config, full_refresh))
        if len(self.calls) >= 2:
            self.started.set()
        try:
            if instrument.symbol not in self.immediate_symbols:
                await self.release.wait()
            else:
                await self.complete_immediate.wait()
            return SyncOutcome(
                instrument_id=instrument.id,
                status="success",
                bar_count=1,
                full_refresh=full_refresh,
            )
        finally:
            self.active -= 1
            if self.active == 0:
                self.quiet.set()


def context_for(
    factory: SessionFactory,
    sync: ControlledSync,
) -> TaskContext:
    settings = default_settings()
    runs = TaskRunRepository(factory)
    run = runs.create_run("fixture.concurrency", "manual")
    return TaskContext(
        run_id=run.id,
        settings=settings,
        resources=RuntimeResources(
            instrument_repository=InstrumentRepository(factory),
            bar_repository=BarRepository(factory),
            provider_registry=ProviderRegistry(
                settings=settings,
                ohlcv_providers={"yfinance": object()},  # type: ignore[dict-item]
            ),
            bar_sync_service=sync,  # type: ignore[arg-type]
        ),
        runs=runs,
    )


@pytest.mark.anyio
async def test_concurrency_is_bounded_and_failures_keep_input_order(
    session_factory: SessionFactory,
) -> None:
    symbols = ("AAA", "BBB", "CCC", "DDD")
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog([instrument_dto(symbol) for symbol in symbols])
    sync = ControlledSync({"AAA": 0.02, "BBB": -0.04, "CCC": -0.01, "DDD": 0.01})
    context = context_for(session_factory, sync)

    result = await USStockDailySyncTask().run(
        context,
        DailySyncParams(symbols=symbols, concurrency=3),
    )

    assert sync.max_active > 1
    assert sync.max_active <= 3
    assert result.progress == 100
    assert result.details["total"] == 4
    assert result.details["succeeded"] == 2
    assert result.details["failed"] == 2
    assert result.details["current_symbol"] == "DDD"
    assert [failure["symbol"] for failure in result.details["failures"]] == [
        "BBB",
        "CCC",
    ]


@pytest.mark.anyio
async def test_default_concurrency_preserves_sequential_execution(
    session_factory: SessionFactory,
) -> None:
    symbols = ("AAA", "BBB")
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog([instrument_dto(symbol) for symbol in symbols])
    sync = ControlledSync({"AAA": 0.02, "BBB": 0.0})
    context = context_for(session_factory, sync)

    result = await USStockDailySyncTask().run(
        context,
        DailySyncParams(symbols=symbols),
    )

    assert sync.max_active == 1
    assert [call[0].symbol for call in sync.calls] == list(symbols)
    assert result.details["succeeded"] == 2
    assert result.details["failed"] == 0


@pytest.mark.anyio
async def test_parent_cancellation_cancels_and_awaits_all_symbol_children(
    session_factory: SessionFactory,
) -> None:
    symbols = ("AAA", "BBB", "CCC")
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog([instrument_dto(symbol) for symbol in symbols])
    sync = BlockingSync()
    context = context_for(session_factory, sync)
    execution = asyncio.create_task(
        USStockDailySyncTask().run(
            context,
            DailySyncParams(symbols=symbols, concurrency=2),
        )
    )
    await asyncio.wait_for(sync.started.wait(), timeout=1)

    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    sync.release.set()
    await asyncio.wait_for(sync.quiet.wait(), timeout=1)

    assert [call[0].symbol for call in sync.calls] == ["AAA", "BBB"]
    assert sync.active == 0


@pytest.mark.anyio
async def test_progress_failure_cancels_and_awaits_all_symbol_children(
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    symbols = ("AAA", "BBB", "CCC")
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog([instrument_dto(symbol) for symbol in symbols])
    sync = BlockingSync(immediate_symbols=frozenset({"AAA"}))
    context = context_for(session_factory, sync)

    def fail_progress(_context: TaskContext, _progress: float) -> None:
        raise RuntimeError("simulated progress persistence failure")

    monkeypatch.setattr(TaskContext, "report_progress", fail_progress)
    execution = asyncio.create_task(
        USStockDailySyncTask().run(
            context,
            DailySyncParams(symbols=symbols, concurrency=2),
        )
    )
    await asyncio.wait_for(sync.started.wait(), timeout=1)
    sync.complete_immediate.set()

    with pytest.raises(RuntimeError, match="progress persistence"):
        await execution
    try:
        assert sync.active == 0
        assert sync.quiet.is_set()
    finally:
        sync.release.set()
        await asyncio.wait_for(sync.quiet.wait(), timeout=1)
