"""Resumable built-in daily OHLCV synchronization Tasks."""

from collections.abc import Iterable
from typing import ClassVar, Literal

from pydantic import BaseModel, field_validator

from app.config.models import MarketSettings
from app.domain.dto import InstrumentRecord, Market
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import ProviderError, sanitize_provider_detail
from app.providers.registry import ProviderRegistry
from app.services.bar_sync_service import BarSyncService, SyncOutcome
from app.services.resources import RuntimeResources
from app.tasks.base import (
    Task,
    TaskContext,
    TaskParams,
    TaskResult,
    require_task_params,
)
from app.tasks.registry import register_task

DEFAULT_MARKET_UNIVERSES: dict[str, tuple[str, ...]] = {
    "a_share": ("csi300", "star_market", "chinext"),
    "hk_stock": ("hstech",),
    "us_stock": ("nasdaq100", "soxx"),
    "crypto": (),
}
DEFAULT_UNIVERSE_ERROR = "No instruments selected for daily market synchronization"
FAILURE_LOG_MESSAGE = "Instrument synchronization failed"
SUCCESS_LOG_MESSAGE = "Instrument synchronization succeeded"


class DailySyncParams(TaskParams):
    """Select current universe members and/or existing canonical symbols."""

    universe_codes: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    full_refresh: bool = False

    @field_validator("universe_codes", "symbols")
    @classmethod
    def values_must_be_nonempty_strings(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("Universe codes and symbols must not be blank")
        return normalized


async def run_daily_sync(
    context: TaskContext,
    params: DailySyncParams,
    market: Market,
) -> TaskResult:
    """Continue after safe per-symbol failures and report durable progress."""
    resources = _resources(context)
    config = context.settings.markets[market]
    configured_crypto = _upsert_crypto_catalog(resources, market, config)
    selected, unresolved = _select_instruments(
        resources,
        market,
        params,
        configured_crypto,
    )
    if not selected and not unresolved:
        raise ValueError(DEFAULT_UNIVERSE_ERROR)

    failures = list(unresolved)
    for failure in unresolved:
        _log_unresolved(context, failure)
    initial_failed = len(failures)
    total = len(selected) + initial_failed
    succeeded = 0
    bar_count = 0
    current_symbol = selected[-1].symbol if selected else None
    for current, instrument in enumerate(selected, start=1):
        current_symbol = instrument.symbol
        try:
            outcome = await _sync_one(
                resources, context.settings.markets[market], instrument, params
            )
        except Exception as error:
            detail = _safe_detail(error)
            failures = [
                *failures,
                {"symbol": instrument.symbol, "detail": detail},
            ]
            context.log(
                "ERROR",
                FAILURE_LOG_MESSAGE,
                run_id=context.run_id,
                symbol=instrument.symbol,
                instrument_id=instrument.id,
                error_type=type(error).__name__,
                detail=detail,
            )
        else:
            succeeded += 1
            bar_count += outcome.bar_count
            context.log(
                "INFO",
                SUCCESS_LOG_MESSAGE,
                run_id=context.run_id,
                symbol=instrument.symbol,
                instrument_id=instrument.id,
                bar_count=outcome.bar_count,
                full_refresh=outcome.full_refresh,
                detail=sanitize_provider_detail(outcome.detail),
            )
        context.report_progress((initial_failed + current) * 100 / total)

    if not selected:
        context.report_progress(100)
    failed = len(failures)
    status = _terminal_status(succeeded, failed)
    details = {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "current": total,
        "current_symbol": current_symbol,
        "bar_count": bar_count,
        "failures": failures,
    }
    return TaskResult(
        status=status,
        details=details,
        error=_result_error(status, failed, total),
    )


async def _sync_one(
    resources: RuntimeResources,
    config: MarketSettings,
    instrument: InstrumentRecord,
    params: DailySyncParams,
) -> SyncOutcome:
    registry = _provider_registry(resources)
    sync = _bar_sync(resources)
    record_config = _record_config(config, instrument)
    provider = registry.get_ohlcv(instrument.market, record_config.provider)
    return await sync.sync_instrument(
        instrument,
        provider,
        record_config,
        full_refresh=params.full_refresh,
    )


def _select_instruments(
    resources: RuntimeResources,
    market: Market,
    params: DailySyncParams,
    configured_crypto: tuple[InstrumentRecord, ...],
) -> tuple[tuple[InstrumentRecord, ...], tuple[dict[str, str], ...]]:
    use_defaults = not params.universe_codes and not params.symbols
    if use_defaults and market == "crypto":
        return _deduplicate(configured_crypto), ()
    codes = DEFAULT_MARKET_UNIVERSES[market] if use_defaults else params.universe_codes
    selected: tuple[InstrumentRecord, ...] = ()
    failures: tuple[dict[str, str], ...] = ()
    for code in dict.fromkeys(codes):
        if not use_defaults and code not in DEFAULT_MARKET_UNIVERSES[market]:
            failures = (
                *failures,
                {
                    "universe_code": code,
                    "detail": "Unknown universe code for this market",
                },
            )
            continue
        members = resources.instrument_repository.list_members(code, market=market)
        active = tuple(record for record in members if record.active)
        if not use_defaults and not active:
            failures = (
                *failures,
                {
                    "universe_code": code,
                    "detail": "Universe selection resolved no active instruments",
                },
            )
        selected = (*selected, *active)
    for symbol in dict.fromkeys(params.symbols):
        record = resources.instrument_repository.get_by_symbol(market, symbol)
        if record is None:
            failures = (
                *failures,
                {
                    "symbol": symbol,
                    "detail": "Requested symbol was not found in the instrument catalog",
                },
            )
        elif not record.active:
            failures = (
                *failures,
                {
                    "symbol": symbol,
                    "detail": "Requested symbol is inactive in the instrument catalog",
                },
            )
        else:
            selected = (*selected, record)
    return _deduplicate(selected), failures


def _deduplicate(
    records: Iterable[InstrumentRecord],
) -> tuple[InstrumentRecord, ...]:
    by_id: dict[int, InstrumentRecord] = {}
    for record in records:
        if record.id not in by_id:
            by_id = {**by_id, record.id: record}
    return tuple(by_id.values())


def _upsert_crypto_catalog(
    resources: RuntimeResources,
    market: Market,
    config: MarketSettings,
) -> tuple[InstrumentRecord, ...]:
    if market != "crypto":
        return ()
    instruments = tuple(crypto_instrument(entry) for entry in config.symbols)
    if not instruments:
        return ()
    return tuple(resources.instrument_repository.upsert_catalog(instruments))


def _record_config(
    config: MarketSettings, instrument: InstrumentRecord
) -> MarketSettings:
    if instrument.market != "crypto":
        return config.model_copy(deep=True)
    provider = instrument.exchange.lower()
    return config.model_copy(deep=True, update={"provider": provider})


def _resources(context: TaskContext) -> RuntimeResources:
    resources = context.resources
    _provider_registry(resources)
    _bar_sync(resources)
    return resources


def _provider_registry(resources: RuntimeResources) -> ProviderRegistry:
    registry = resources.provider_registry
    if registry is None:
        raise RuntimeError("Market provider registry is not configured")
    return registry


def _bar_sync(resources: RuntimeResources) -> BarSyncService:
    service = resources.bar_sync_service
    if service is None:
        raise RuntimeError("Bar synchronization service is not configured")
    return service


def _log_unresolved(context: TaskContext, failure: dict[str, str]) -> None:
    context.log(
        "ERROR",
        FAILURE_LOG_MESSAGE,
        run_id=context.run_id,
        symbol=failure.get("symbol"),
        universe_code=failure.get("universe_code"),
        error_type="UnresolvedSelection",
        detail=failure["detail"],
    )


def _safe_detail(error: Exception) -> str:
    if isinstance(error, ProviderError):
        return error.public_detail
    return FAILURE_LOG_MESSAGE


def _terminal_status(
    succeeded: int, failed: int
) -> Literal["success", "partial", "failed"]:
    if failed == 0:
        return "success"
    if succeeded == 0:
        return "failed"
    return "partial"


def _result_error(status: str, failed: int, total: int) -> str | None:
    if status == "success":
        return None
    if status == "failed":
        return "All instrument synchronizations failed"
    return f"{failed} of {total} instrument synchronizations failed"


class MarketDailyTask(Task):
    """Shared validated entry point for the four concrete market Tasks."""

    market: ClassVar[Market]
    params_model: ClassVar[type[BaseModel]] = DailySyncParams

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        validated = require_task_params(params, DailySyncParams)
        return await run_daily_sync(context, validated, self.market)


@register_task
class AShareDailySyncTask(MarketDailyTask):
    name: ClassVar[str] = "market.sync_a_daily"
    display_name: ClassVar[str] = "Synchronize A-share daily bars"
    description: ClassVar[str] = "Resume A-share OHLCV synchronization"
    market: ClassVar[Market] = "a_share"


@register_task
class HKStockDailySyncTask(MarketDailyTask):
    name: ClassVar[str] = "market.sync_hk_daily"
    display_name: ClassVar[str] = "Synchronize Hong Kong daily bars"
    description: ClassVar[str] = "Resume Hong Kong OHLCV synchronization"
    market: ClassVar[Market] = "hk_stock"


@register_task
class USStockDailySyncTask(MarketDailyTask):
    name: ClassVar[str] = "market.sync_us_daily"
    display_name: ClassVar[str] = "Synchronize US daily bars"
    description: ClassVar[str] = "Resume US OHLCV synchronization"
    market: ClassVar[Market] = "us_stock"


@register_task
class CryptoDailySyncTask(MarketDailyTask):
    name: ClassVar[str] = "market.sync_crypto_daily"
    display_name: ClassVar[str] = "Synchronize crypto daily bars"
    description: ClassVar[str] = "Resume exchange-scoped crypto OHLCV synchronization"
    market: ClassVar[Market] = "crypto"


SyncADailyTask = AShareDailySyncTask
SyncHKDailyTask = HKStockDailySyncTask
SyncUSDailyTask = USStockDailySyncTask
SyncCryptoDailyTask = CryptoDailySyncTask

__all__ = [
    "AShareDailySyncTask",
    "CryptoDailySyncTask",
    "DailySyncParams",
    "HKStockDailySyncTask",
    "SyncADailyTask",
    "SyncCryptoDailyTask",
    "SyncHKDailyTask",
    "SyncUSDailyTask",
    "USStockDailySyncTask",
]
