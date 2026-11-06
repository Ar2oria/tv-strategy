"""Finite Wilder RSI with configurable reference lines."""

import math
from collections.abc import Sequence
from typing import ClassVar, Self

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.domain.dto import BarDTO
from app.indicators.base import (
    Indicator,
    IndicatorContext,
    IndicatorParams,
    require_params,
    snapshot_bars,
)
from app.indicators.models import (
    IndicatorResult,
    PaneDefinition,
    ReferenceLine,
    SeriesDefinition,
    SeriesPoint,
)
from app.indicators.registry import register_indicator

NEUTRAL_COLOR = "#2962ff"
OVERBOUGHT_COLOR = "#d1345b"
OVERSOLD_COLOR = "#168b5b"


class RSIParams(IndicatorParams):
    """Wilder smoothing window and ordered oscillator thresholds."""

    window: int = Field(default=14, ge=2, le=200)
    oversold: float = Field(default=30.0, ge=0.0, le=100.0)
    overbought: float = Field(default=70.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> Self:
        if self.oversold >= self.overbought:
            raise ValueError("RSI oversold must be lower than overbought")
        return self


@register_indicator
class RSIIndicator(Indicator):
    """Calculate Wilder-smoothed RSI without leaking division NaN or infinity."""

    name: ClassVar[str] = "rsi"
    display_name: ClassVar[str] = "Relative Strength Index"
    description: ClassVar[str] = "Wilder RSI with configurable horizontal thresholds"
    params_model: ClassVar[type[BaseModel]] = RSIParams

    def calculate(
        self,
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        params: BaseModel,
    ) -> IndicatorResult:
        options = require_params(params, RSIParams)
        snapshot = snapshot_bars(bars)
        if len(snapshot) <= options.window:
            warning = (
                f"RSI window={options.window} needs at least "
                f"{options.window + 1} bars; series is empty."
            )
            return _result(options, (), (warning,))
        closes = pd.Series((bar.close for bar in snapshot), dtype="float64")
        if bool((closes == closes.iloc[0]).all()):
            return _result(
                options,
                (),
                ("RSI is undefined for constant prices; series is empty.",),
            )

        points, flat_periods = _rsi_points(snapshot, closes, options)
        warnings = (
            ("Flat periods with no gains or losses were omitted.",)
            if flat_periods
            else ()
        )
        return _result(options, points, warnings)


def _rsi_points(
    bars: tuple[BarDTO, ...],
    closes: pd.Series,
    options: RSIParams,
) -> tuple[tuple[SeriesPoint, ...], bool]:
    delta = closes.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    average_gain = float(gains.iloc[1 : options.window + 1].mean())
    average_loss = float(losses.iloc[1 : options.window + 1].mean())

    points: list[SeriesPoint] = []
    flat_periods = False
    for index in range(options.window, len(bars)):
        if index > options.window:
            average_gain = (
                average_gain * (options.window - 1) + float(gains.iloc[index])
            ) / options.window
            average_loss = (
                average_loss * (options.window - 1) + float(losses.iloc[index])
            ) / options.window
        if average_gain == 0.0 and average_loss == 0.0:
            flat_periods = True
            continue
        value = _bounded_rsi(average_gain, average_loss)
        points.append(
            SeriesPoint(
                time=bars[index].time,
                value=value,
                color=_point_color(value, options),
            )
        )
    return tuple(points), flat_periods


def _bounded_rsi(gain: float, loss: float) -> float:
    if loss == 0.0:
        return 100.0
    if gain == 0.0:
        return 0.0
    value = 100.0 - (100.0 / (1.0 + (gain / loss)))
    if not math.isfinite(value):
        return 100.0 if gain > loss else 0.0
    return min(100.0, max(0.0, value))


def _point_color(value: float, options: RSIParams) -> str | None:
    if value >= options.overbought:
        return OVERBOUGHT_COLOR
    if value <= options.oversold:
        return OVERSOLD_COLOR
    return None


def _result(
    options: RSIParams,
    points: tuple[SeriesPoint, ...],
    warnings: tuple[str, ...],
) -> IndicatorResult:
    return IndicatorResult(
        panes=(PaneDefinition(id="rsi", title="RSI", height=160),),
        series=(
            SeriesDefinition(
                id="rsi",
                pane_id="rsi",
                type="line",
                title=f"RSI ({options.window})",
                points=points,
                color=NEUTRAL_COLOR,
            ),
        ),
        reference_lines=(
            ReferenceLine(
                series_id="rsi",
                value=options.oversold,
                color=OVERSOLD_COLOR,
                title=f"Oversold {options.oversold:g}",
            ),
            ReferenceLine(
                series_id="rsi",
                value=options.overbought,
                color=OVERBOUGHT_COLOR,
                title=f"Overbought {options.overbought:g}",
            ),
        ),
        warnings=warnings,
    )
