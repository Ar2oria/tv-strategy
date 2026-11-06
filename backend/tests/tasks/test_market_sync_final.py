"""Unresolved selections, diagnostics, and configured universe Task timeouts."""

from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import update

from app.config.defaults import default_settings
from app.config.models import MarketSettings, Settings
from app.db.database import SessionFactory
from app.domain.dto import InstrumentRecord, UniverseSnapshot
from app.models.instrument import Instrument
from app.providers.errors import ProviderDataInvalid
from app.providers.registry import ProviderRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.repositories.task_runs import TaskRunRepository
from app.services.bar_sync_service import SyncOutcome
from app.services.resources import RuntimeResources
from app.services.universe_sync_service import UniverseSyncOutcome, UniverseSyncService
from app.tasks.base import TaskContext
from app.tasks.builtin.sync_daily import DailySyncParams, USStockDailySyncTask
from app.tasks.builtin.sync_universes import SyncUniversesTask, UniverseSyncParams
from tests.market_sync_fixtures import instrument_dto, market_config

RAW_SECRET = "https://user:secret@example.test/private?api_key=supersecret"


def settings_with(market: MarketSettings | None = None) -> Settings:
    settings = default_settings()
    if market is None:
        return settings
    return Settings.model_validate(
        settings.model_copy(
            update={"markets": {**settings.markets, "us_stock": market}}
        ).model_dump(mode="python")
    )


def context_for(
    factory: SessionFactory,
    resources: RuntimeResources,
    settings: Settings,
) -> TaskContext:
    runs = TaskRunRepository(factory)
    run = runs.create_run("fixture.market-final", "manual")
    return TaskContext(
        run_id=run.id,
        settings=settings,
        resources=resources,
        runs=runs,
    )


def resources_for(
    factory: SessionFactory,
    settings: Settings,
    sync: object,
    *,
    universe_providers: dict[str, object] | None = None,
) -> RuntimeResources:
    return RuntimeResources(
        instrument_repository=InstrumentRepository(factory),
        bar_repository=BarRepository(factory),
        provider_registry=ProviderRegistry(
            settings=settings,
            ohlcv_providers={"yfinance": object()},  # type: ignore[dict-item]
            universe_providers=universe_providers or {},  # type: ignore[arg-type]
        ),
        bar_sync_service=sync,  # type: ignore[arg-type]
    )


class RecordingSync:
    def __init__(self, *, error: Exception | None = None, detail: str | None = None) -> None:
        self.error = error
        self.detail = detail
        self.calls: list[InstrumentRecord] = []

    async def sync_instrument(
        self,
        instrument: InstrumentRecord,
        provider: object,
        config: MarketSettings,
        full_refresh: bool = False,
    ) -> SyncOutcome:
        self.calls.append(instrument)
        if self.error is not None:
            raise self.error
        return SyncOutcome(
            instrument.id,
            "success",
            0,
            full_refresh,
            self.detail,
        )


def replace_universe(
    repository: InstrumentRepository,
    code: str,
    *symbols: str,
) -> None:
    repository.replace_universe(
        UniverseSnapshot(
            universe_code=code,
            source="fixture",
            effective_date=date(2026, 1, 30),
            members=tuple(instrument_dto(symbol) for symbol in symbols),
        )
    )


@pytest.mark.anyio
async def test_mixed_valid_missing_symbol_is_partial_and_success_detail_is_logged(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog(instrument_dto("AAA"))
    settings = settings_with(market_config())
    sync = RecordingSync(detail="No new bars were available")
    resources = resources_for(session_factory, settings, sync)
    context = context_for(session_factory, resources, settings)

    result = await USStockDailySyncTask().run(
        context,
        DailySyncParams(symbols=("AAA", "MISSING")),
    )

    assert result.status == "partial"
    assert result.details["total"] == 2
    assert result.details["succeeded"] == 1
    assert result.details["failed"] == 1
    assert [record.symbol for record in sync.calls] == ["AAA"]
    assert result.details["failures"] == [
        {"symbol": "MISSING", "detail": "Requested symbol was not found in the instrument catalog"}
    ]
    logs = context.runs.list_logs(context.run_id)
    success = next(log for log in logs if log.level == "INFO")
    failure = next(log for log in logs if log.level == "ERROR")
    assert success.context["detail"] == "No new bars were available"
    assert failure.context["symbol"] == "MISSING"
    assert "not found" in failure.context["detail"]


@pytest.mark.anyio
async def test_all_missing_and_inactive_symbols_fail_without_provider_access(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    inactive = instruments.upsert_catalog(instrument_dto("INACTIVE"))[0]
    with session_factory() as session:
        session.execute(
            update(Instrument).where(Instrument.id == inactive.id).values(active=False)
        )
        session.commit()
    settings = settings_with(market_config())
    sync = RecordingSync()
    context = context_for(
        session_factory,
        resources_for(session_factory, settings, sync),
        settings,
    )

    result = await USStockDailySyncTask().run(
        context,
        DailySyncParams(symbols=("MISSING", "INACTIVE")),
    )

    assert result.status == "failed"
    assert result.details["total"] == 2
    assert result.details["succeeded"] == 0
    assert result.details["failed"] == 2
    assert sync.calls == []
    assert result.details["failures"] == [
        {"symbol": "MISSING", "detail": "Requested symbol was not found in the instrument catalog"},
        {"symbol": "INACTIVE", "detail": "Requested symbol is inactive in the instrument catalog"},
    ]


@pytest.mark.anyio
async def test_unknown_daily_universe_is_a_failed_item_while_valid_code_continues(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    replace_universe(instruments, "nasdaq100", "AAA")
    settings = settings_with(market_config())
    sync = RecordingSync()
    context = context_for(
        session_factory,
        resources_for(session_factory, settings, sync),
        settings,
    )

    result = await USStockDailySyncTask().run(
        context,
        DailySyncParams(universe_codes=("nasdaq100", "not-a-universe")),
    )

    assert result.status == "partial"
    assert result.details["total"] == 2
    assert result.details["succeeded"] == 1
    assert result.details["failed"] == 1
    assert result.details["failures"] == [
        {"universe_code": "not-a-universe", "detail": "Unknown universe code for this market"}
    ]
    assert [record.symbol for record in sync.calls] == ["AAA"]


@pytest.mark.anyio
async def test_all_unknown_daily_universes_return_failed_not_empty_success(
    session_factory: SessionFactory,
) -> None:
    settings = settings_with(market_config())
    sync = RecordingSync()
    context = context_for(
        session_factory,
        resources_for(session_factory, settings, sync),
        settings,
    )

    result = await USStockDailySyncTask().run(
        context,
        DailySyncParams(universe_codes=("not-a-universe",)),
    )

    assert result.status == "failed"
    assert result.details["total"] == 1
    assert result.details["succeeded"] == 0
    assert result.details["failed"] == 1
    assert sync.calls == []


@pytest.mark.anyio
async def test_provider_detail_is_actionable_and_raw_upstream_cause_is_absent(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog(instrument_dto("AAA"))
    settings = settings_with(market_config())
    error = ProviderDataInvalid("Yahoo response is missing OHLCV columns")
    error.__cause__ = RuntimeError(RAW_SECRET)
    context = context_for(
        session_factory,
        resources_for(session_factory, settings, RecordingSync(error=error)),
        settings,
    )

    result = await USStockDailySyncTask().run(
        context,
        DailySyncParams(symbols=("AAA",)),
    )

    assert result.status == "failed"
    assert "missing OHLCV columns" in result.details["failures"][0]["detail"]
    logs = context.runs.list_logs(context.run_id)
    failure = next(log for log in logs if log.level == "ERROR")
    assert "missing OHLCV columns" in failure.context["detail"]
    assert RAW_SECRET not in str(logs)
    assert "supersecret" not in str(logs)
    assert "example.test" not in str(logs)


@pytest.mark.anyio
async def test_universe_task_preserves_sanitized_provider_detail(
    session_factory: SessionFactory,
) -> None:
    settings = default_settings()
    error = ProviderDataInvalid("HSTECH declared constituent count mismatch")
    error.__cause__ = RuntimeError(RAW_SECRET)
    provider = Mock()
    provider.fetch_universe.side_effect = error
    context = context_for(
        session_factory,
        resources_for(
            session_factory,
            settings,
            RecordingSync(),
            universe_providers={"csi300": provider},
        ),
        settings,
    )

    result = await SyncUniversesTask().run(
        context,
        UniverseSyncParams(universe_codes=("csi300",)),
    )

    assert result.status == "failed"
    assert "declared constituent count mismatch" in result.details["failures"][0]["detail"]
    logs = context.runs.list_logs(context.run_id)
    assert "declared constituent count mismatch" in logs[0].context["detail"]
    assert "supersecret" not in str(logs)


@pytest.mark.anyio
async def test_empty_universe_preserves_no_data_actionable_detail(
    session_factory: SessionFactory,
) -> None:
    settings = default_settings()
    provider = Mock()
    provider.fetch_universe.return_value = UniverseSnapshot(
        universe_code="csi300",
        source="fixture",
        effective_date=None,
        members=(),
    )
    context = context_for(
        session_factory,
        resources_for(
            session_factory,
            settings,
            RecordingSync(),
            universe_providers={"csi300": provider},
        ),
        settings,
    )

    result = await SyncUniversesTask().run(
        context,
        UniverseSyncParams(universe_codes=("csi300",)),
    )

    assert result.status == "failed"
    assert "contains no members" in result.details["failures"][0]["detail"]
    assert "contains no members" in context.runs.list_logs(context.run_id)[0].context["detail"]


@pytest.mark.anyio
async def test_universe_task_passes_owning_market_timeout_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
) -> None:
    settings = settings_with(market_config(request_timeout_seconds=12.75))
    provider = Mock()
    context = context_for(
        session_factory,
        resources_for(
            session_factory,
            settings,
            RecordingSync(),
            universe_providers={"soxx": provider},
        ),
        settings,
    )
    timeouts: list[float | None] = []

    async def fake_sync(
        self: UniverseSyncService,
        code: str,
        selected_provider: object,
        *,
        timeout: float | None = None,
    ) -> UniverseSyncOutcome:
        timeouts.append(timeout)
        return UniverseSyncOutcome(code, "success", 1, 1)

    monkeypatch.setattr(UniverseSyncService, "sync_universe", fake_sync)

    result = await SyncUniversesTask().run(
        context,
        UniverseSyncParams(universe_codes=("soxx",)),
    )

    assert result.status == "success"
    assert timeouts == [12.75]
