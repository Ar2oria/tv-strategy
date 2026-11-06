"""Donchian channels built strictly from previous bars."""

from collections.abc import Sequence
from typing import ClassVar

import pandas as pd
from pydantic import BaseModel, Field

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
    MarkerDefinition,
    PaneDefinition,
    SeriesDefinition,
    SeriesPoint,
)
from app.indicators.registry import register_indicator

UP_COLOR = "#168b5b"
DOWN_COLOR = "#d1345b"


class DonchianParams(IndicatorParams):
    """Previous-bar channel width."""

    window: int = Field(default=20, ge=1, le=200)


@register_indicator
class DonchianBreakoutIndicator(Indicator):
    """Mark closes outside the highest high or lowest low of previous bars."""

    name: ClassVar[str] = "donchian"
    display_name: ClassVar[str] = "Donchian Breakout"
    description: ClassVar[str] = (
        "Previous N-bar channel with arrows for closing-price breakouts"
    )
    params_model: ClassVar[type[BaseModel]] = DonchianParams

    def calculate(
        self,
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        params: BaseModel,
    ) -> IndicatorResult:
        options = require_params(params, DonchianParams)
        snapshot = snapshot_bars(bars)
        highs = pd.Series((bar.high for bar in snapshot), dtype="float64")
        lows = pd.Series((bar.low for bar in snapshot), dtype="float64")
        upper = highs.rolling(
            options.window, min_periods=options.window
        ).max().shift(1)
        lower = lows.rolling(
            options.window, min_periods=options.window
        ).min().shift(1)

        upper_points: list[SeriesPoint] = []
        lower_points: list[SeriesPoint] = []
        markers: list[MarkerDefinition] = []
        for index, bar in enumerate(snapshot):
            if pd.isna(upper.iloc[index]) or pd.isna(lower.iloc[index]):
                continue
            upper_value = float(upper.iloc[index])
            lower_value = float(lower.iloc[index])
            upper_points.append(SeriesPoint(time=bar.time, value=upper_value))
            lower_points.append(SeriesPoint(time=bar.time, value=lower_value))
            marker = _breakout_marker(
                bar, options.window, upper_value, lower_value
            )
            if marker is not None:
                markers.append(marker)

        warnings = _warnings(len(snapshot), options.window, bool(markers))
        return _result(options.window, upper_points, lower_points, markers, warnings)


def _breakout_marker(
    bar: BarDTO,
    window: int,
    upper: float,
    lower: float,
) -> MarkerDefinition | None:
    if bar.close > upper:
        return MarkerDefinition(
            time=bar.time,
            position="belowBar",
            shape="arrowUp",
            color=UP_COLOR,
            text="Up breakout",
            tooltip=(
                f"Close {bar.close:g} above previous {window}-bar high {upper:g}"
            ),
        )
    if bar.close < lower:
        return MarkerDefinition(
            time=bar.time,
            position="aboveBar",
            shape="arrowDown",
            color=DOWN_COLOR,
            text="Down breakout",
            tooltip=f"Close {bar.close:g} below previous {window}-bar low {lower:g}",
        )
    return None


def _warnings(bar_count: int, window: int, has_breakouts: bool) -> tuple[str, ...]:
    if bar_count <= window:
        return (
            f"Donchian window={window} needs at least {window + 1} bars; "
            "channel and markers are empty.",
        )
    if not has_breakouts:
        return ("No Donchian closing-price breakouts were detected.",)
    return ()


def _result(
    window: int,
    upper_points: list[SeriesPoint],
    lower_points: list[SeriesPoint],
    markers: list[MarkerDefinition],
    warnings: tuple[str, ...],
) -> IndicatorResult:
    return IndicatorResult(
        panes=(PaneDefinition(id="main", title="Price", height=400),),
        series=(
            SeriesDefinition(
                id="upper",
                pane_id="main",
                type="line",
                title=f"Previous {window}-bar high",
                points=tuple(upper_points),
                color=UP_COLOR,
            ),
            SeriesDefinition(
                id="lower",
                pane_id="main",
                type="line",
                title=f"Previous {window}-bar low",
                points=tuple(lower_points),
                color=DOWN_COLOR,
            ),
        ),
        markers=tuple(markers),
        warnings=warnings,
    )
