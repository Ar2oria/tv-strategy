"""Indicator cache entry lifecycle, slicing, invalidation, and eviction tests."""

from datetime import date, timedelta

from app.domain.dto import BarDTO
from app.indicators.models import (
    IndicatorResult,
    PaneDefinition,
    SeriesDefinition,
    SeriesPoint,
)
from app.services.indicator_cache import (
    IndicatorCache,
    indicator_cache_key,
    params_digest,
)


def series_result(count: int) -> IndicatorResult:
    day = date(2026, 1, 1)
    points = tuple(
        SeriesPoint(time=day + timedelta(days=index), value=float(index))
        for index in range(count)
    )
    definition = SeriesDefinition(
        id="value", pane_id="panel", type="line", title="V"
    )
    return IndicatorResult(
        panes=(PaneDefinition(id="panel", title="Panel"),),
        series=(definition.model_copy(update={"points": points}),),
    )


def test_params_digest_is_order_insensitive_and_changes_with_input() -> None:
    assert params_digest({"window": 14, "overbought": 70}) == params_digest(
        {"overbought": 70, "window": 14}
    )
    assert params_digest({"window": 14}) != params_digest({"window": 21})
    assert len(params_digest({"window": 14})) == 16


def test_cache_key_covers_all_inputs() -> None:
    base = indicator_cache_key(3, "1d", "rsi", params_digest({"window": 14}))
    assert base != indicator_cache_key(4, "1d", "rsi", params_digest({"window": 14}))
    assert base != indicator_cache_key(3, "1w", "rsi", params_digest({"window": 14}))
    assert base != indicator_cache_key(3, "1d", "macd", params_digest({"window": 14}))
    assert base != indicator_cache_key(3, "1d", "rsi", params_digest({"window": 21}))


def test_miss_then_store_then_hit_returns_same_result() -> None:
    cache = IndicatorCache()
    key = indicator_cache_key(3, "1d", "rsi", params_digest({"window": 14}))
    assert cache.get(key, watermark=date(2026, 12, 31)) is None
    result = series_result(3)
    cache.store(key, result, watermark=date(2026, 12, 31))
    assert cache.get(key, watermark=date(2026, 12, 31)) is not None
    hit = cache.get(key, watermark=date(2026, 12, 31))
    assert hit is not None
    assert hit.series[0].points == result.series[0].points

def test_stale_watermark_is_a_miss() -> None:
    cache = IndicatorCache()
    key = indicator_cache_key(3, "1d", "rsi", params_digest({"window": 14}))
    cache.store(key, series_result(3), watermark=date(2026, 12, 31))
    newer = cache.get(key, watermark=date(2027, 1, 5))
    assert newer is None
    assert cache.get(key, watermark=date(2026, 12, 31)) is not None

def test_expiry_after_one_hour_is_a_miss() -> None:
    now = {"value": 1000.0}
    cache = IndicatorCache(clock=lambda: now["value"])
    key = indicator_cache_key(3, "1d", "rsi", params_digest({"window": 14}))
    cache.store(key, series_result(3), watermark=date(2026, 12, 31))
    assert cache.get(key, watermark=date(2026, 12, 31)) is not None
    now["value"] += 3601.0
    assert cache.get(key, watermark=date(2026, 12, 31)) is None

def test_invalidate_instrument_drops_only_that_instrument() -> None:
    cache = IndicatorCache()
    key_a = indicator_cache_key(3, "1d", "rsi", params_digest({"window": 14}))
    key_b = indicator_cache_key(4, "1d", "rsi", params_digest({"window": 14}))
    watermark = date(2026, 12, 31)
    cache.store(key_a, series_result(3), watermark=watermark)
    cache.store(key_b, series_result(3), watermark=watermark)
    cache.invalidate_instrument(3)
    assert cache.get(key_a, watermark=watermark) is None
    assert cache.get(key_b, watermark=watermark) is not None

def test_lru_eviction_over_point_budget() -> None:
    cache = IndicatorCache(max_total_points=10)
    watermark = date(2026, 12, 31)
    first = indicator_cache_key(1, "1d", "a", params_digest({}))
    second = indicator_cache_key(1, "1d", "b", params_digest({}))
    cache.store(first, series_result(6), watermark=watermark)
    cache.store(second, series_result(6), watermark=watermark)
    third = indicator_cache_key(1, "1d", "c", params_digest({}))
    cache.store(third, series_result(4), watermark=watermark)
    # 6 + 6 + 4 = 16 > 10 evicts the oldest entry first; 6 + 4 = 10 fits.
    assert cache.get(first, watermark=watermark) is None
    assert cache.get(second, watermark=watermark) is not None
    assert cache.get(third, watermark=watermark) is not None

def test_get_refreshes_lru_recency() -> None:
    cache = IndicatorCache(max_total_points=10)
    watermark = date(2026, 12, 31)
    first = indicator_cache_key(1, "1d", "a", params_digest({}))
    second = indicator_cache_key(1, "1d", "b", params_digest({}))
    cache.store(first, series_result(4), watermark=watermark)
    cache.store(second, series_result(4), watermark=watermark)
    # Touching first makes second the least recently used instead.
    assert cache.get(first, watermark=watermark) is not None
    third = indicator_cache_key(1, "1d", "c", params_digest({}))
    cache.store(third, series_result(4), watermark=watermark)
    assert cache.get(first, watermark=watermark) is not None
    assert cache.get(second, watermark=watermark) is None
    assert cache.get(third, watermark=watermark) is not None

def test_store_returns_the_stored_result_for_callers() -> None:
    cache = IndicatorCache()
    key = indicator_cache_key(3, "1d", "rsi", params_digest({"window": 14}))
    stored = cache.store(key, series_result(3), watermark=date(2026, 12, 31))
    assert stored is not None
    assert stored.series[0].points == series_result(3).series[0].points
