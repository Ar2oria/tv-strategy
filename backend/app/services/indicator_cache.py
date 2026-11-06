"""In-memory full-result cache for computed indicators.

Keyed by (instrument, timeframe, indicator name, params digest). Entries hold
the complete un-trimmed ``IndicatorResult`` together with the data watermark
(the latest DB bar date covered by the computation), so requests can slice any
window out of the cached list. Expiry is a hard-coded one hour; bar syncs
invalidate per instrument. Compute runs inside ``asyncio.to_thread``, so all
access is guarded by one lock.
"""

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import date
from typing import Any

from app.indicators.models import IndicatorResult

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600.0
DEFAULT_MAX_TOTAL_POINTS = 2_000_000


def params_digest(params: dict[str, Any]) -> str:
    """Hash arbitrary validated params into a stable 16-hex digest."""
    payload = json.dumps(
        params, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def indicator_cache_key(
    instrument_id: int,
    timeframe: str,
    indicator_name: str,
    digest: str,
) -> tuple[int, str, str, str]:
    """Build the composite cache key for one indicator computation."""
    return (instrument_id, timeframe, indicator_name, digest)


def _result_points(result: IndicatorResult) -> int:
    return sum(len(series.points) for series in result.series)


class IndicatorCache:
    """Bounded LRU of full computed results with watermark validity."""

    def __init__(
        self,
        *,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_total_points: int = DEFAULT_MAX_TOTAL_POINTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_total_points = max_total_points
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[
            tuple[int, str, str, str],
            tuple[IndicatorResult, date, float],
        ] = OrderedDict()
        self._total_points = 0

    def get(
        self,
        key: tuple[int, str, str, str],
        *,
        watermark: date,
    ) -> IndicatorResult | None:
        """Return the cached result when fresh and covering the watermark."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            result, stored_watermark, stored_at = entry
            if self._clock() - stored_at >= self._ttl_seconds:
                self._evict_locked(key, result)
                return None
            if stored_watermark < watermark:
                return None
            self._entries.move_to_end(key)
            return result.model_copy(deep=True)

    def store(
        self,
        key: tuple[int, str, str, str],
        result: IndicatorResult,
        *,
        watermark: date,
    ) -> IndicatorResult | None:
        """Store a detached copy; returns None when it exceeds the budget."""
        points = _result_points(result)
        if points > self._max_total_points:
            logger.info(
                "Indicator cache rejects an entry of %d points (budget %d)",
                points,
                self._max_total_points,
            )
            return None
        stored = result.model_copy(deep=True)
        with self._lock:
            if key in self._entries:
                previous = self._entries[key][0]
                self._evict_locked(key, previous)
            self._entries[key] = (stored, watermark, self._clock())
            self._total_points += points
            self._evict_over_budget_locked()
        return stored

    def invalidate_instrument(self, instrument_id: int) -> None:
        """Drop every entry computed for one instrument after a bar sync."""
        with self._lock:
            stale = [
                key for key in self._entries if key[0] == instrument_id
            ]
            for key in stale:
                result, _, _ = self._entries[key]
                self._evict_locked(key, result)

    def _evict_locked(
        self,
        key: tuple[int, str, str, str],
        result: IndicatorResult,
    ) -> None:
        self._total_points -= _result_points(result)
        self._entries.pop(key, None)

    def _evict_over_budget_locked(self) -> None:
        while self._total_points > self._max_total_points and self._entries:
            key, (result, _, _) = next(iter(self._entries.items()))
            self._evict_locked(key, result)
