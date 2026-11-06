"""Atomic daily-bar downloads, adjustment detection, and bounded retries."""

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.config.models import MarketSettings
from app.domain.dto import Adjustment, BarDTO, InstrumentRecord
from app.providers.base import OhlcvProvider
from app.providers.errors import (
    NoDataAvailable,
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.validation import PRICE_FIELDS, validate_bars
from app.repositories.bars import BarRepository
from app.services.indicator_cache import IndicatorCache
from app.services.provider_calls import call_provider_sync

OHLC_RELATIVE_TOLERANCE = 1e-6
OHLC_ABSOLUTE_TOLERANCE = 1e-8
RETRY_BASE_SECONDS = 1.0
RETRY_MAX_SECONDS = 30.0
FULL_REPLACEMENT_DETAIL = "Source or OHLC adjustment change required full replacement"
INCREMENTAL_EMPTY_DETAIL = "No new bars were available"
RETRYABLE_PROVIDER_ERRORS = (ProviderUnavailable, ProviderRateLimited)


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """Successful per-instrument write or up-to-date no-op summary."""

    instrument_id: int
    status: Literal["success"]
    bar_count: int
    full_refresh: bool
    detail: str | None = None


class BarSyncService:
    """Synchronize one instrument without exposing partial provider responses."""

    def __init__(
        self,
        bar_repository: BarRepository,
        *,
        today: Callable[[], date] = date.today,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        cache: IndicatorCache | None = None,
    ) -> None:
        if not callable(today) or not callable(sleep):
            raise TypeError("today and sleep must be callable")
        self._bars = bar_repository
        self._today = today
        self._sleep = sleep
        self._cache = cache

    async def sync_instrument(
        self,
        instrument: InstrumentRecord,
        provider: OhlcvProvider,
        config: MarketSettings,
        full_refresh: bool = False,
    ) -> SyncOutcome:
        """Fetch completely, then upsert or atomically replace one series."""
        if not isinstance(instrument, InstrumentRecord):
            raise TypeError("instrument must be an InstrumentRecord")
        if not isinstance(config, MarketSettings):
            raise TypeError("config must be MarketSettings")
        if not isinstance(full_refresh, bool):
            raise TypeError("full_refresh must be a boolean")
        end = self._end_date()
        adjustment = _adjustment_for(instrument)
        existing = tuple(self._bars.get_all_until(instrument.id, end))
        source_changed = _source_or_adjustment_changed(
            existing, config.provider, adjustment
        )
        requires_full = full_refresh or not existing or source_changed
        start = (
            _full_history_start(end, config.history_years)
            if requires_full
            else existing[-1].time - timedelta(days=config.overlap_days)
        )
        downloaded = await self._fetch(
            provider, instrument, start, end, adjustment, config
        )
        if not downloaded:
            return _empty_outcome(instrument.id, requires_full)
        if requires_full:
            _require_complete_full_history(existing, downloaded, start, end)
            return self._replace(instrument.id, downloaded, detail=None)
        if _overlap_requires_replacement(existing, downloaded):
            complete = await self._fetch(
                provider,
                instrument,
                _full_history_start(end, config.history_years),
                end,
                adjustment,
                config,
            )
            if not complete:
                raise NoDataAvailable()
            _require_complete_full_history(
                existing,
                complete,
                _full_history_start(end, config.history_years),
                end,
            )
            return self._replace(
                instrument.id, complete, detail=FULL_REPLACEMENT_DETAIL
            )
        count = self._bars.upsert(instrument.id, downloaded)
        self._invalidate_cache(instrument.id)
        return SyncOutcome(instrument.id, "success", count, False)

    async def _fetch(
        self,
        provider: OhlcvProvider,
        instrument: InstrumentRecord,
        start: date | None,
        end: date,
        adjustment: Adjustment,
        config: MarketSettings,
    ) -> tuple[BarDTO, ...]:
        for attempt in range(config.max_retries + 1):
            try:
                rows = await call_provider_sync(
                    provider.fetch_daily,
                    instrument,
                    start,
                    end,
                    adjustment,
                    timeout=config.request_timeout_seconds,
                )
                validated = tuple(validate_bars(rows))
                if any(
                    (start is not None and row.time < start) or row.time > end
                    for row in validated
                ):
                    raise ProviderDataInvalid(
                        "Provider bars are outside the requested range"
                    )
                if any(
                    row.source != config.provider or row.adjustment != adjustment
                    for row in validated
                ):
                    raise ProviderDataInvalid(
                        "Provider bars have unexpected source or adjustment metadata"
                    )
                return validated
            except RETRYABLE_PROVIDER_ERRORS as error:
                if attempt >= config.max_retries:
                    raise
                await self._sleep(_retry_delay(attempt, error))
        raise AssertionError("retry loop always returns or raises")

    def _replace(
        self,
        instrument_id: int,
        rows: Sequence[BarDTO],
        *,
        detail: str | None,
    ) -> SyncOutcome:
        count = self._bars.replace_all(instrument_id, rows)
        self._invalidate_cache(instrument_id)
        return SyncOutcome(instrument_id, "success", count, True, detail)

    def _invalidate_cache(self, instrument_id: int) -> None:
        if self._cache is not None:
            self._cache.invalidate_instrument(instrument_id)

    def _end_date(self) -> date:
        value = self._today()
        if not isinstance(value, date) or type(value) is not date:
            raise ProviderDataInvalid("Synchronization clock must return a date")
        return value


def _empty_outcome(instrument_id: int, requires_full: bool) -> SyncOutcome:
    if requires_full:
        raise NoDataAvailable()
    return SyncOutcome(
        instrument_id,
        "success",
        0,
        False,
        INCREMENTAL_EMPTY_DETAIL,
    )


def _adjustment_for(instrument: InstrumentRecord) -> Adjustment:
    if instrument.instrument_type in {"index", "crypto_spot"}:
        return "none"
    return "qfq"


def _full_history_start(end: date, history_years: int | None) -> date | None:
    if history_years is None:
        return None
    if isinstance(history_years, bool) or history_years < 1:
        raise ValueError("history_years must be positive or None")
    try:
        return end.replace(year=end.year - history_years)
    except ValueError:
        return end.replace(year=end.year - history_years, day=28)


def _source_or_adjustment_changed(
    existing: tuple[BarDTO, ...], source: str, adjustment: Adjustment
) -> bool:
    return any(row.source != source or row.adjustment != adjustment for row in existing)


def _require_complete_full_history(
    existing: tuple[BarDTO, ...],
    downloaded: tuple[BarDTO, ...],
    start: date | None,
    end: date,
) -> None:
    existing_in_range = tuple(
        row
        for row in existing
        if (start is None or row.time >= start) and row.time <= end
    )
    if (
        existing_in_range
        and downloaded[0].time > existing_in_range[0].time
    ):
        raise ProviderDataInvalid(
            "Full provider history starts after existing stored history; "
            "refusing an incomplete replacement"
        )
    if existing_in_range and downloaded[-1].time < existing_in_range[-1].time:
        raise ProviderDataInvalid(
            "Full provider history ends before existing stored history; "
            "refusing an incomplete replacement"
        )
    existing_dates = frozenset(row.time for row in existing_in_range)
    downloaded_dates = frozenset(row.time for row in downloaded)
    if existing_dates - downloaded_dates:
        raise ProviderDataInvalid(
            "Full provider history is missing existing dates; "
            "refusing an incomplete replacement"
        )


def _overlap_requires_replacement(
    existing: tuple[BarDTO, ...], downloaded: tuple[BarDTO, ...]
) -> bool:
    stored_by_date = {row.time: row for row in existing}
    for incoming in downloaded:
        stored = stored_by_date.get(incoming.time)
        if stored is None:
            continue
        if incoming.source != stored.source or incoming.adjustment != stored.adjustment:
            return True
        if any(
            not math.isclose(
                getattr(incoming, field),
                getattr(stored, field),
                rel_tol=OHLC_RELATIVE_TOLERANCE,
                abs_tol=OHLC_ABSOLUTE_TOLERANCE,
            )
            for field in PRICE_FIELDS
        ):
            return True
    return False


def _retry_delay(attempt: int, error: Exception) -> float:
    exponential = min(RETRY_BASE_SECONDS * (2**attempt), RETRY_MAX_SECONDS)
    upstream = getattr(error, "retry_after", None)
    if (
        isinstance(upstream, (int, float))
        and not isinstance(upstream, bool)
        and math.isfinite(upstream)
        and upstream >= 0
    ):
        exponential = max(exponential, float(upstream))
    return exponential
