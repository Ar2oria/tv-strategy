"""Offline built-in market Task orchestration and container replacement tests."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from app.bootstrap import build_container
from app.config.application import AppSettings
from app.config.defaults import default_settings
from app.config.models import CryptoSymbol, MarketSettings, Settings
from app.config.store import ConfigApplyError
from app.db.database import SessionFactory
from app.domain.dto import InstrumentDTO, InstrumentRecord, UniverseSnapshot
from app.providers.akshare_ohlcv import AkshareOhlcvProvider
from app.providers.baostock_ohlcv import BaoStockOhlcvProvider
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import ProviderUnavailable
from app.providers.hstech_api import ItigerUniverseProvider
from app.providers.registry import ProviderRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.repositories.task_runs import TaskRunRepository
from app.services.bar_sync_service import BarSyncOptions, BarSyncService, SyncOutcome
from app.services.resources import RuntimeResources
from app.tasks.base import TaskContext
from app.tasks.builtin.sync_daily import (
    AShareDailySyncTask,
    CryptoDailySyncParams,
    CryptoDailySyncTask,
    DEFAULT_UNIVERSE_ERROR,
    DailySyncParams,
    HKStockDailySyncTask,
    USStockDailySyncTask,
)
from app.tasks.builtin.sync_universes import SyncUniversesTask, UniverseSyncParams
from app.tasks.discovery import discover_tasks
from tests.market_sync_fixtures import TODAY, bar, instrument_dto, market_config

TASK_NAMES = {
    "market.sync_universes",
    "market.sync_a_daily",
    "market.sync_hk_daily",
    "market.sync_us_daily",
    "market.sync_crypto_daily",
}


def test_daily_sync_params_default_to_market_independent_options() -> None:
    params = DailySyncParams()

    assert params.history_years is None
    assert params.overlap_days == 45
    assert params.concurrency == 1
    assert params.adjustment == "auto"


@pytest.mark.parametrize(
    "changes",
    [
        {"history_years": 0},
        {"overlap_days": 0},
        {"overlap_days": 367},
        {"concurrency": 0},
        {"concurrency": 9},
        {"adjustment": "adjusted"},
    ],
)
def test_daily_sync_params_reject_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        DailySyncParams(**changes)  # type: ignore[arg-type]


def test_daily_sync_params_allow_null_history_and_explicit_adjustments() -> None:
    assert DailySyncParams(history_years=None).history_years is None
    assert DailySyncParams(adjustment="qfq").adjustment == "qfq"
    assert DailySyncParams(adjustment="none").adjustment == "none"


@dataclass(frozen=True, slots=True)
class ContextHarness:
    context: TaskContext
    runs: TaskRunRepository


def settings_with(
    market: str,
    config: MarketSettings | BarSyncOptions,
) -> Settings:
    settings = default_settings()
    market_settings = (
        config
        if isinstance(config, MarketSettings)
        else MarketSettings(
            provider=config.provider,
            request_timeout_seconds=config.request_timeout_seconds,
        )
    )
    candidate = settings.model_copy(
        update={"markets": {**settings.markets, market: market_settings}}
    )
    return Settings.model_validate(candidate.model_dump(mode="python"))


def crypto_settings() -> Settings:
    return settings_with("crypto", MarketSettings(provider="binance"))


def make_context(
    factory: SessionFactory,
    resources: RuntimeResources,
    settings: Settings,
) -> ContextHarness:
    runs = TaskRunRepository(factory)
    run = runs.create_run("fixture.market", "manual")
    return ContextHarness(
        TaskContext(
            run_id=run.id,
            settings=settings,
            resources=resources,
            runs=runs,
        ),
        runs,
    )


class RecordingSync:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.calls: list[tuple[InstrumentRecord, object, BarSyncOptions, bool]] = []

    async def sync_instrument(
        self,
        instrument: InstrumentRecord,
        provider: object,
        config: BarSyncOptions,
        full_refresh: bool = False,
    ) -> SyncOutcome:
        self.calls.append((instrument, provider, config, full_refresh))
        if instrument.symbol in self.failing:
            raise ProviderUnavailable("private-token-and-upstream-url")
        return SyncOutcome(
            instrument_id=instrument.id,
            status="success",
            bar_count=1,
            full_refresh=full_refresh,
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
async def test_daily_task_deduplicates_universes_and_returns_sanitized_partial(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    replace_universe(instruments, "nasdaq100", "AAA", "BBB")
    replace_universe(instruments, "soxx", "AAA", "CCC")
    settings = settings_with("us_stock", market_config())
    sync = RecordingSync(failing={"BBB"})
    marker_provider = object()
    registry = ProviderRegistry(
        settings=settings,
        ohlcv_providers={"yfinance": marker_provider},  # type: ignore[dict-item]
    )
    resources = RuntimeResources(
        instrument_repository=instruments,
        bar_repository=BarRepository(session_factory),
        provider_registry=registry,
        bar_sync_service=sync,  # type: ignore[arg-type]
    )
    harness = make_context(session_factory, resources, settings)

    result = await USStockDailySyncTask().run(
        harness.context,
        DailySyncParams(universe_codes=("nasdaq100", "soxx"), full_refresh=True),
    )

    assert result.status == "partial"
    assert result.progress == 100
    assert result.details["total"] == 3
    assert result.details["succeeded"] == 2
    assert result.details["failed"] == 1
    assert result.details["current"] == 3
    assert [call[0].symbol for call in sync.calls].count("AAA") == 1
    assert len(sync.calls) == 3
    assert all(call[1] is marker_provider for call in sync.calls)
    assert all(call[3] is True for call in sync.calls)
    logs = harness.runs.list_logs(harness.context.run_id)
    failure = next(log for log in logs if log.level == "ERROR")
    assert failure.context["symbol"] == "BBB"
    assert failure.context["run_id"] == harness.context.run_id
    assert "private-token" not in str(logs)


@pytest.mark.anyio
async def test_daily_task_returns_failed_when_every_instrument_fails(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    records = instruments.upsert_catalog([instrument_dto("AAA"), instrument_dto("BBB")])
    assert len(records) == 2
    settings = settings_with("us_stock", market_config())
    sync = RecordingSync(failing={"AAA", "BBB"})
    resources = RuntimeResources(
        instrument_repository=instruments,
        bar_repository=BarRepository(session_factory),
        provider_registry=ProviderRegistry(
            settings=settings, ohlcv_providers={"yfinance": object()}  # type: ignore[dict-item]
        ),
        bar_sync_service=sync,  # type: ignore[arg-type]
    )
    harness = make_context(session_factory, resources, settings)

    result = await USStockDailySyncTask().run(
        harness.context,
        DailySyncParams(symbols=("AAA", "BBB")),
    )

    assert result.status == "failed"
    assert result.details == {
        "total": 2,
        "succeeded": 0,
        "failed": 2,
        "current": 2,
        "current_symbol": "BBB",
        "bar_count": 0,
        "failures": [
            {"symbol": "AAA", "detail": "Market-data provider is unavailable"},
            {"symbol": "BBB", "detail": "Market-data provider is unavailable"},
        ],
    }


@pytest.mark.anyio
async def test_all_unresolved_daily_symbols_fail_before_provider_access(
    session_factory: SessionFactory,
) -> None:
    settings = settings_with("us_stock", market_config())
    sync = RecordingSync()
    resources = RuntimeResources(
        instrument_repository=InstrumentRepository(session_factory),
        bar_repository=BarRepository(session_factory),
        provider_registry=ProviderRegistry(settings=settings),
        bar_sync_service=sync,  # type: ignore[arg-type]
    )
    harness = make_context(session_factory, resources, settings)

    result = await USStockDailySyncTask().run(
        harness.context, DailySyncParams(symbols=("MISSING",))
    )

    assert result.status == "failed"
    assert result.details["total"] == 1
    assert result.details["succeeded"] == 0
    assert result.details["failed"] == 1
    assert sync.calls == []


class ResumeProvider:
    def __init__(self) -> None:
        self.calls: dict[str, int] = defaultdict(int)

    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: str,
    ) -> list[object]:
        self.calls[instrument.symbol] += 1
        if instrument.symbol == "CCC" and self.calls[instrument.symbol] == 1:
            raise ProviderUnavailable()
        if instrument.symbol != "CCC" and self.calls[instrument.symbol] > 1:
            return []
        return [bar(TODAY)]


@pytest.mark.anyio
async def test_interrupted_three_instrument_run_resumes_without_duplicates(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog(
        [instrument_dto(symbol) for symbol in ("AAA", "BBB", "CCC")]
    )
    bars = BarRepository(session_factory)
    settings = settings_with("us_stock", market_config())
    provider = ResumeProvider()
    registry = ProviderRegistry(
        settings=settings, ohlcv_providers={"yfinance": provider}  # type: ignore[dict-item]
    )
    sync = BarSyncService(bars, today=lambda: TODAY)
    resources = RuntimeResources(
        instrument_repository=instruments,
        bar_repository=bars,
        provider_registry=registry,
        bar_sync_service=sync,
    )
    first = make_context(session_factory, resources, settings)
    params = DailySyncParams(symbols=("AAA", "BBB", "CCC"))

    first_result = await USStockDailySyncTask().run(first.context, params)
    second = make_context(session_factory, resources, settings)
    second_result = await USStockDailySyncTask().run(second.context, params)

    assert first_result.status == "partial"
    assert first_result.details["succeeded"] == 2
    assert second_result.status == "success"
    assert second_result.details["succeeded"] == 3
    for record in instruments.list_instruments(market="us_stock"):
        stored = bars.get_all_until(record.id, TODAY)
        assert len(stored) == 1
        assert stored[0].time == TODAY
    assert dict(provider.calls) == {"AAA": 2, "BBB": 2, "CCC": 2}


class ExchangeProvider:
    def __init__(self, exchange: str) -> None:
        self.exchange = exchange
        self.instruments: list[InstrumentDTO] = []

    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: str,
    ) -> list[object]:
        self.instruments.append(instrument)
        assert instrument.exchange == self.exchange
        return [bar(TODAY, source=self.exchange, adjustment="none")]


@pytest.mark.anyio
async def test_crypto_task_upserts_exchange_qualified_records_and_separates_series(
    session_factory: SessionFactory,
) -> None:
    settings = crypto_settings()
    instruments = InstrumentRepository(session_factory)
    bars = BarRepository(session_factory)
    binance = ExchangeProvider("binance")
    okx = ExchangeProvider("okx")
    registry = ProviderRegistry(
        settings=settings,
        ohlcv_providers={"binance": binance, "okx": okx},  # type: ignore[dict-item]
    )
    resources = RuntimeResources(
        instrument_repository=instruments,
        bar_repository=bars,
        provider_registry=registry,
        bar_sync_service=BarSyncService(bars, today=lambda: TODAY),
    )
    harness = make_context(session_factory, resources, settings)

    result = await CryptoDailySyncTask().run(
        harness.context,
        CryptoDailySyncParams(
            spot_pairs=(
                CryptoSymbol(exchange="binance", symbol="BTC/USDT"),
                CryptoSymbol(exchange="okx", symbol="BTC/USDT"),
            )
        ),
    )

    assert result.status == "success"
    records = instruments.list_instruments(market="crypto")
    assert [record.symbol for record in records] == [
        "BINANCE:BTC/USDT",
        "OKX:BTC/USDT",
    ]
    assert records[0].id != records[1].id
    assert "OKX:IGNORED/USDT" not in [record.symbol for record in records]
    for record in records:
        stored = bars.get_all_until(record.id, TODAY)
        assert len(stored) == 1
        assert stored[0].source == record.exchange
    assert [item.exchange for item in binance.instruments] == ["binance"]
    assert [item.exchange for item in okx.instruments] == ["okx"]


@pytest.mark.anyio
async def test_crypto_empty_task_directory_ignores_market_fallback(
    session_factory: SessionFactory,
) -> None:
    settings = crypto_settings()
    sync = RecordingSync()
    resources = RuntimeResources(
        instrument_repository=InstrumentRepository(session_factory),
        bar_repository=BarRepository(session_factory),
        provider_registry=ProviderRegistry(settings=settings),
        bar_sync_service=sync,  # type: ignore[arg-type]
    )
    harness = make_context(session_factory, resources, settings)

    result = await CryptoDailySyncTask().run(
        harness.context, CryptoDailySyncParams()
    )

    assert result.status == "failed"
    assert result.progress == 100
    assert result.error is not None
    assert "Configure spot_pairs or symbols" in result.error
    logs = harness.runs.list_logs(harness.context.run_id)
    assert [log.level for log in logs] == ["ERROR"]
    assert logs[0].context["error_type"] == "EmptyInstrumentSelection"
    assert sync.calls == []


@pytest.mark.anyio
async def test_empty_default_us_catalog_returns_actionable_failure_and_log(
    session_factory: SessionFactory,
) -> None:
    settings = settings_with("us_stock", market_config())
    sync = RecordingSync()
    resources = RuntimeResources(
        instrument_repository=InstrumentRepository(session_factory),
        bar_repository=BarRepository(session_factory),
        provider_registry=ProviderRegistry(settings=settings),
        bar_sync_service=sync,  # type: ignore[arg-type]
    )
    harness = make_context(session_factory, resources, settings)

    result = await USStockDailySyncTask().run(harness.context, DailySyncParams())

    assert result.status == "failed"
    assert result.progress == 100
    assert result.error is not None
    assert DEFAULT_UNIVERSE_ERROR in result.error
    assert "Run Synchronize market universes first" in result.error
    logs = harness.runs.list_logs(harness.context.run_id)
    assert [log.level for log in logs] == ["ERROR"]
    assert logs[0].context["error_type"] == "EmptyInstrumentSelection"
    assert "Run Synchronize market universes first" in logs[0].context["detail"]
    assert sync.calls == []


@pytest.mark.anyio
async def test_crypto_explicit_symbols_use_only_existing_local_catalog(
    session_factory: SessionFactory,
) -> None:
    settings = crypto_settings()
    instruments = InstrumentRepository(session_factory)
    instruments.upsert_catalog(
        crypto_instrument(CryptoSymbol(exchange="okx", symbol="ETH/USDT"))
    )
    sync = RecordingSync()
    resources = RuntimeResources(
        instrument_repository=instruments,
        bar_repository=BarRepository(session_factory),
        provider_registry=ProviderRegistry(
            settings=settings,
            ohlcv_providers={"okx": object()},  # type: ignore[dict-item]
        ),
        bar_sync_service=sync,  # type: ignore[arg-type]
    )
    harness = make_context(session_factory, resources, settings)

    result = await CryptoDailySyncTask().run(
        harness.context,
        CryptoDailySyncParams(symbols=("OKX:ETH/USDT",)),
    )

    assert result.status == "success"
    assert [call[0].symbol for call in sync.calls] == ["OKX:ETH/USDT"]
    assert [record.symbol for record in instruments.list_instruments(market="crypto")] == [
        "OKX:ETH/USDT"
    ]


@pytest.mark.anyio
async def test_crypto_unknown_explicit_symbol_does_not_import_market_pairs(
    session_factory: SessionFactory,
) -> None:
    settings = crypto_settings()
    instruments = InstrumentRepository(session_factory)
    sync = RecordingSync()
    resources = RuntimeResources(
        instrument_repository=instruments,
        bar_repository=BarRepository(session_factory),
        provider_registry=ProviderRegistry(settings=settings),
        bar_sync_service=sync,  # type: ignore[arg-type]
    )
    harness = make_context(session_factory, resources, settings)

    result = await CryptoDailySyncTask().run(
        harness.context,
        CryptoDailySyncParams(symbols=("OKX:MISSING/USDT",)),
    )

    assert result.status == "failed"
    assert sync.calls == []
    assert instruments.list_instruments(market="crypto") == []


class StaticUniverseProvider:
    def __init__(self, response: object) -> None:
        self.response = response

    def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response  # type: ignore[return-value]


@pytest.mark.anyio
async def test_universe_task_is_partial_and_preserves_failed_universe(
    session_factory: SessionFactory,
) -> None:
    instruments = InstrumentRepository(session_factory)
    replace_universe(instruments, "csi300", "OLD")
    replacement = UniverseSnapshot(
        universe_code="soxx",
        source="fixture",
        effective_date=None,
        members=(instrument_dto("NEW"),),
    )
    settings = default_settings()
    registry = ProviderRegistry(
        settings=settings,
        universe_providers={
            "csi300": StaticUniverseProvider(ProviderUnavailable("secret")),
            "soxx": StaticUniverseProvider(replacement),
        },
    )
    resources = RuntimeResources(
        instrument_repository=instruments,
        bar_repository=BarRepository(session_factory),
        provider_registry=registry,
    )
    harness = make_context(session_factory, resources, settings)

    result = await SyncUniversesTask().run(
        harness.context,
        UniverseSyncParams(universe_codes=("csi300", "soxx")),
    )

    assert result.status == "partial"
    assert result.details["total"] == 2
    assert result.details["succeeded"] == 1
    assert result.details["failed"] == 1
    assert [item.symbol for item in instruments.list_members("csi300")] == ["OLD"]
    assert [item.symbol for item in instruments.list_members("soxx")] == ["NEW"]
    assert "secret" not in str(harness.runs.list_logs(harness.context.run_id))


@pytest.mark.anyio
async def test_hstech_task_uses_token_override_without_logging_it(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
) -> None:
    settings = default_settings()
    token = "override-secret-token"
    expected = UniverseSnapshot(
        universe_code="hstech",
        source="itiger",
        effective_date=None,
        members=(instrument_dto("0700.HK"),),
    )
    calls: list[str] = []

    def fake_fetch(**kwargs: object) -> UniverseSnapshot:
        calls.append(str(kwargs["bearer_token"]))
        return expected

    monkeypatch.setattr("app.providers.hstech_api.fetch_hstech_api_snapshot", fake_fetch)
    registry = ProviderRegistry(
        settings=settings,
        universe_providers={"hstech": ItigerUniverseProvider(bearer_token="initial-token")},
    )
    resources = RuntimeResources(
        instrument_repository=InstrumentRepository(session_factory),
        bar_repository=BarRepository(session_factory),
        provider_registry=registry,
    )
    harness = make_context(session_factory, resources, settings)

    result = await SyncUniversesTask().run(
        harness.context,
        UniverseSyncParams(universe_codes=("hstech",), itiger_token=token),
    )

    assert result.status == "success"
    assert calls == [token]
    assert token not in str(harness.runs.list_logs(harness.context.run_id))


def test_market_tasks_have_unique_registered_names() -> None:
    registry = discover_tasks()

    assert TASK_NAMES <= {descriptor.name for descriptor in registry.descriptors}
    assert registry.get("market.sync_a_daily").task_class is AShareDailySyncTask
    assert registry.get("market.sync_hk_daily").task_class is HKStockDailySyncTask
    assert registry.get("market.sync_us_daily").task_class is USStockDailySyncTask
    assert registry.get("market.sync_crypto_daily").task_class is CryptoDailySyncTask


def test_container_registers_adapters_and_hot_replacement_reaches_new_task_runs(
    tmp_path: Path,
) -> None:
    app_settings = AppSettings(
        config_path=tmp_path / "settings.json",
        database_path=tmp_path / "hot.sqlite3",
    )
    container = build_container(app_settings)
    try:
        original_resources = container.resources
        original_registry = container.provider_registry
        assert isinstance(original_registry, ProviderRegistry)
        assert isinstance(original_registry.get_ohlcv("a_share"), AkshareOhlcvProvider)
        assert original_resources.bar_sync_service is not None

        current = container.config_service.get()
        changed_market = current.markets["a_share"].model_copy(
            update={"provider": "baostock"}
        )
        candidate = Settings.model_validate(
            current.model_copy(
                update={"markets": {**current.markets, "a_share": changed_market}}
            ).model_dump(mode="python")
        )
        container.apply_provider_settings(candidate)

        replacement_resources = container.resources
        replacement_registry = container.provider_registry
        assert replacement_registry is not original_registry
        assert isinstance(
            replacement_registry.get_ohlcv("a_share"), BaoStockOhlcvProvider
        )
        assert isinstance(original_registry.get_ohlcv("a_share"), AkshareOhlcvProvider)
        assert container.task_runner.resources is replacement_resources
        assert original_resources.provider_registry is original_registry

        failed_once = False

        def reject_once(settings: Settings) -> None:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise RuntimeError("listener failed")

        container.config_service.subscribe(container.apply_provider_settings)
        container.config_service.subscribe(reject_once)
        with pytest.raises(ConfigApplyError):
            container.config_service.update(
                current.revision,
                lambda old: old.model_copy(update={"timezone": "Asia/Shanghai"}),
            )

        restored_registry = container.provider_registry
        assert isinstance(restored_registry, ProviderRegistry)
        assert isinstance(restored_registry.get_ohlcv("a_share"), AkshareOhlcvProvider)
        assert container.task_runner.resources is container.resources
    finally:
        container.session_factory.dispose()
