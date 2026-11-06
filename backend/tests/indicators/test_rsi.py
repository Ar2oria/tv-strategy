"""Wilder RSI warmup, extremes, and edge-case behavior."""

import math
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.domain.dto import BarDTO
from app.indicators.base import IndicatorContext
from app.indicators.builtin.rsi import RSIIndicator, RSIParams
from app.indicators.validation import validate_result

CONTEXT = IndicatorContext(symbol="TEST")


def calculate(bars: list[BarDTO], **params: int | float):
    return RSIIndicator().calculate(CONTEXT, bars, RSIParams(**params))


def test_wilder_sma_seed_and_subsequent_recurrence_match_known_answers(
    bar_factory: Callable[..., BarDTO],
) -> None:
    closes = [10.0, 11.0, 10.5, 12.0, 13.0]
    bars = [bar_factory(day + 1, close) for day, close in enumerate(closes)]

    result = calculate(bars, window=3)

    points = result.series[0].points
    assert [point.time for point in points] == [bars[3].time, bars[4].time]
    # Seed: average gain=(1 + 0 + 1.5)/3, average loss=(0 + 0.5 + 0)/3.
    assert points[0].value == pytest.approx(250.0 / 3.0)
    # Next delta=1: averages recur to 8/9 and 1/9, giving RSI=800/9.
    assert points[1].value == pytest.approx(800.0 / 9.0)


def test_only_gains_are_100_after_warmup(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [bar_factory(day + 1, float(day + 1)) for day in range(7)]

    result = calculate(bars, window=3)

    points = result.series[0].points
    assert points
    assert points[0].time == bars[3].time
    assert all(point.value == 100.0 for point in points)
    assert result.warnings == ()
    validate_result(result, {bar.time for bar in bars})


def test_only_losses_are_zero_after_warmup(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [bar_factory(day + 1, float(20 - day)) for day in range(7)]

    result = calculate(bars, window=3)

    assert result.series[0].points
    assert all(point.value == 0.0 for point in result.series[0].points)


def test_reference_lines_and_point_colors_are_configurable(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [bar_factory(day + 1, float(day + 1)) for day in range(7)]

    result = calculate(bars, window=3, oversold=25.0, overbought=75.0)

    assert [line.value for line in result.reference_lines] == [25.0, 75.0]
    assert {line.series_id for line in result.reference_lines} == {"rsi"}
    assert all(point.color == "#d1345b" for point in result.series[0].points)


@pytest.mark.parametrize("bar_count", [0, 1, 3])
def test_empty_and_short_inputs_return_empty_series_with_warning(
    bar_factory: Callable[..., BarDTO],
    bar_count: int,
) -> None:
    bars = [bar_factory(day + 1, float(day + 1)) for day in range(bar_count)]

    result = calculate(bars, window=3)

    assert result.series[0].points == ()
    assert result.warnings
    assert result.reference_lines


def test_constant_prices_return_empty_series_with_warning(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [bar_factory(day + 1, 10.0) for day in range(7)]

    result = calculate(bars, window=3)

    assert result.series[0].points == ()
    assert result.warnings


def test_mixed_prices_never_emit_nan_or_infinity(
    bar_factory: Callable[..., BarDTO],
) -> None:
    closes = [10.0, 11.0, 10.5, 12.0, 12.0, 11.0, 11.5, 13.0]
    bars = [bar_factory(day + 1, close) for day, close in enumerate(closes)]

    result = calculate(bars, window=3)

    assert result.series[0].points
    assert all(
        math.isfinite(point.value) and 0.0 <= point.value <= 100.0
        for point in result.series[0].points
    )
    validate_result(result, {bar.time for bar in bars})


def test_calculation_does_not_mutate_caller_bars(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [bar_factory(day + 1, 10.0 + day) for day in range(7)]
    before = list(bars)

    first = calculate(bars, window=3)
    second = calculate(bars, window=3)

    assert bars == before
    assert first == second
    assert first is not second


def test_rsi_parameters_are_frozen_and_ordered() -> None:
    params = RSIParams()

    with pytest.raises(ValidationError):
        params.window = 20
    with pytest.raises(ValidationError):
        RSIParams(window=1)
    with pytest.raises(ValidationError):
        RSIParams(oversold=80.0, overbought=70.0)
