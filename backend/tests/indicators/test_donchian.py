"""Previous-window Donchian channel and breakout behavior."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.domain.dto import BarDTO
from app.indicators.base import IndicatorContext
from app.indicators.builtin.donchian import (
    DonchianBreakoutIndicator,
    DonchianParams,
)
from app.indicators.validation import validate_result

CONTEXT = IndicatorContext(symbol="TEST")


def calculate(bars: list[BarDTO], window: int = 3):
    return DonchianBreakoutIndicator().calculate(
        CONTEXT,
        bars,
        DonchianParams(window=window),
    )


def test_previous_three_bars_define_channel_and_upward_breakout(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [
        bar_factory(1, 9.0, high=10.0, low=8.0),
        bar_factory(2, 10.0, high=11.0, low=7.0),
        bar_factory(3, 11.0, high=12.0, low=6.0),
        bar_factory(4, 13.0, high=20.0, low=9.0),
    ]

    result = calculate(bars)

    upper = next(item for item in result.series if item.id == "upper")
    lower = next(item for item in result.series if item.id == "lower")
    assert upper.points[-1].value == 12.0
    assert lower.points[-1].value == 6.0
    assert len(result.markers) == 1
    marker = result.markers[0]
    assert marker.time == bars[-1].time
    assert marker.shape == "arrowUp"
    assert marker.position == "belowBar"
    assert "previous 3-bar high" in (marker.tooltip or "")
    validate_result(result, {bar.time for bar in bars})


def test_downward_breakout_has_above_bar_arrow(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [
        bar_factory(1, 9.0, high=10.0, low=8.0),
        bar_factory(2, 10.0, high=11.0, low=7.0),
        bar_factory(3, 11.0, high=12.0, low=6.0),
        bar_factory(4, 5.0, high=13.0, low=4.0),
    ]

    result = calculate(bars)

    assert len(result.markers) == 1
    assert result.markers[0].shape == "arrowDown"
    assert result.markers[0].position == "aboveBar"


def test_current_bar_extreme_is_not_in_its_reference_channel(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [
        bar_factory(1, 9.0, high=10.0, low=8.0),
        bar_factory(2, 10.0, high=11.0, low=7.0),
        bar_factory(3, 11.0, high=12.0, low=6.0),
        bar_factory(4, 11.5, high=100.0, low=1.0),
    ]

    result = calculate(bars)

    upper = next(item for item in result.series if item.id == "upper")
    lower = next(item for item in result.series if item.id == "lower")
    assert upper.points[-1].value == 12.0
    assert lower.points[-1].value == 6.0
    assert result.markers == ()


@pytest.mark.parametrize("bar_count", [0, 1, 3])
def test_empty_and_short_inputs_return_explicit_warning(
    bar_factory: Callable[..., BarDTO],
    bar_count: int,
) -> None:
    bars = [bar_factory(day + 1, 10.0 + day) for day in range(bar_count)]

    result = calculate(bars)

    assert result.warnings
    assert result.markers == ()
    assert all(item.points == () for item in result.series)


def test_constant_prices_produce_finite_channels_and_no_breakouts(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [
        bar_factory(day, 10.0, high=10.0, low=10.0)
        for day in range(1, 7)
    ]

    result = calculate(bars)

    assert result.warnings
    assert result.markers == ()
    assert all(point.value == 10.0 for item in result.series for point in item.points)
    validate_result(result, {bar.time for bar in bars})


def test_calculation_does_not_mutate_caller_bars(
    bar_factory: Callable[..., BarDTO],
) -> None:
    bars = [bar_factory(day + 1, 10.0 + day) for day in range(5)]
    before = list(bars)

    first = calculate(bars)
    second = calculate(bars)

    assert bars == before
    assert first == second
    assert first is not second


def test_donchian_parameters_are_frozen_and_bounded() -> None:
    params = DonchianParams()

    with pytest.raises(ValidationError):
        params.window = 5
    with pytest.raises(ValidationError):
        DonchianParams(window=0)
