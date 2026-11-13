"""Resumable built-in daily OHLCV synchronization Tasks."""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from app.config.models import CryptoSymbol, MarketSettings
from app.domain.dto import InstrumentRecord, Market
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import ProviderError, sanitize_provider_detail
from app.providers.registry import ProviderRegistry
from app.services.bar_sync_service import BarSyncOptions, BarSyncService, SyncOutcome
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
EMPTY_CRYPTO_DIRECTORY_ERROR = (
    "No crypto instruments selected for daily synchronization. "
    "Configure spot_pairs or symbols first"
)
FAILURE_LOG_MESSAGE = "Instrument synchronization failed"
SUCCESS_LOG_MESSAGE = "Instrument synchronization succeeded"


@dataclass(frozen=True, slots=True)
class _Attempt:
    index: int
    instrument: InstrumentRecord
    outcome: SyncOutcome | None
    detail: str | None
    error_type: str | None


class DailySyncParams(TaskParams):
    """Select instruments and control one market's daily synchronization."""

    universe_codes: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    full_refresh: bool = False
    history_years: int | None = Field(default=None, ge=1)
    overlap_days: int = Field(default=45, ge=1, le=366)
    concurrency: int = Field(default=1, ge=1, le=8)
    adjustment: Literal["auto", "qfq", "none"] = "auto"

    @field_validator("universe_codes", "symbols")
    @classmethod
    def values_must_be_nonempty_strings(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("Universe codes and symbols must not be blank")
        return normalized


class CryptoDailySyncParams(DailySyncParams):
    """Daily options plus the default exchange-qualified crypto catalog."""

    spot_pairs: tuple[CryptoSymbol, ...] = ()


async def run_daily_sync(
    context: TaskContext,
    params: DailySyncParams,
    market: Market,
) -> TaskResult:
    """Continue after safe per-symbol failures and report durable progress."""
    resources = _resources(context)
    config = context.settings.markets[market]
    configured_crypto = _upsert_crypto_catalog(resources, market, params)
    selected, unresolved = _select_instruments(
        resources,
        market,
        params,
        configured_crypto,
    )
    if not selected and not unresolved:
        return _empty_selection_result(context, market)

    failures = list(unresolved)
    for failure in unresolved:
        _log_unresolved(context, failure)
    initial_failed = len(failures)
    total = len(selected) + initial_failed
    attempts = await _download_selected(
        resources,
        context,
        config,
        selected,
        params,
        total,
        initial_failed,
    )

    succeeded = 0
    bar_count = 0
    for attempt in attempts:
        if attempt.outcome is None:
            failures = [
                *failures,
                {"symbol": attempt.instrument.symbol, "detail": attempt.detail},
            ]
        else:
            succeeded += 1
            bar_count += attempt.outcome.bar_count

    if not selected:
        context.report_progress(100)
    failed = len(failures)
    status = _terminal_status(succeeded, failed)
    details = {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "current": total,
        "current_symbol": selected[-1].symbol if selected else None,
        "bar_count": bar_count,
        "failures": failures,
    }
    return TaskResult(
        status=status,
        details=details,
        error=_result_error(status, failed, total),
    )


def _empty_selection_result(context: TaskContext, market: Market) -> TaskResult:
    error = (
        EMPTY_CRYPTO_DIRECTORY_ERROR
        if market == "crypto"
        else f"{DEFAULT_UNIVERSE_ERROR}. Run Synchronize market universes first"
    )
    context.log(
        "ERROR",
        error,
        run_id=context.run_id,
        error_type="EmptyInstrumentSelection",
        detail=error,
    )
    context.report_progress(100)
    return TaskResult(
        status="failed",
        progress=100,
        error=error,
        details={
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "current": 0,
            "current_symbol": None,
            "bar_count": 0,
            "failures": [],
        },
    )


async def _download_selected(
    resources: RuntimeResources,
    context: TaskContext,
    config: MarketSettings,
    selected: tuple[InstrumentRecord, ...],
    params: DailySyncParams,
    total: int,
    initial_failed: int,
) -> tuple[_Attempt, ...]:
    semaphore = asyncio.Semaphore(params.concurrency)

    async def bounded(index: int, instrument: InstrumentRecord) -> _Attempt:
        async with semaphore:
            return await _attempt(resources, config, instrument, params, index)

    tasks = [
        asyncio.create_task(bounded(index, instrument))
        for index, instrument in enumerate(selected)
    ]
    attempts: list[_Attempt] = []
    try:
        for completed, future in enumerate(asyncio.as_completed(tasks), start=1):
            attempt = await future
            attempts.append(attempt)
            _log_attempt(context, attempt, completed, total, initial_failed)
        return tuple(sorted(attempts, key=lambda attempt: attempt.index))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _attempt(
    resources: RuntimeResources,
    config: MarketSettings,
    instrument: InstrumentRecord,
    params: DailySyncParams,
    index: int,
) -> _Attempt:
    try:
        outcome = await _sync_one(resources, config, instrument, params)
    except Exception as error:
        return _Attempt(index, instrument, None, _safe_detail(error), type(error).__name__)
    return _Attempt(index, instrument, outcome, None, None)


def _log_attempt(
    context: TaskContext,
    attempt: _Attempt,
    completed: int,
    total: int,
    initial_failed: int,
) -> None:
    instrument = attempt.instrument
    if attempt.outcome is None:
        context.log(
            "ERROR",
            FAILURE_LOG_MESSAGE,
            run_id=context.run_id,
            symbol=instrument.symbol,
            instrument_id=instrument.id,
            error_type=attempt.error_type,
            detail=attempt.detail,
        )
    else:
        context.log(
            "INFO",
            SUCCESS_LOG_MESSAGE,
            run_id=context.run_id,
            symbol=instrument.symbol,
            instrument_id=instrument.id,
            bar_count=attempt.outcome.bar_count,
            full_refresh=attempt.outcome.full_refresh,
            detail=sanitize_provider_detail(attempt.outcome.detail),
        )
    context.report_progress((initial_failed + completed) * 100 / total)


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
    options = _sync_options(record_config, instrument, params)
    return await sync.sync_instrument(
        instrument,
        provider,
        options,
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
    params: DailySyncParams,
) -> tuple[InstrumentRecord, ...]:
    if market != "crypto":
        return ()
    crypto_params = require_task_params(params, CryptoDailySyncParams)
    instruments = tuple(crypto_instrument(entry) for entry in crypto_params.spot_pairs)
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


def _sync_options(
    config: MarketSettings,
    instrument: InstrumentRecord,
    params: DailySyncParams,
) -> BarSyncOptions:
    history_years = params.history_years
    if history_years is None and instrument.market != "crypto":
        history_years = 10
    return BarSyncOptions(
        provider=config.provider,
        history_years=history_years,
        overlap_days=params.overlap_days,
        adjustment=params.adjustment,
        request_timeout_seconds=config.request_timeout_seconds,
    )


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
    params_model: ClassVar[type[BaseModel]] = CryptoDailySyncParams


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
