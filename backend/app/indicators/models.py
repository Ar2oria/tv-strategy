"""Frozen, JSON-serializable indicator output models."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_IDENTIFIER_LENGTH = 255
IDENTIFIER_PATTERN = (
    rf"^[A-Za-z0-9][A-Za-z0-9_.:-]{{0,{MAX_IDENTIFIER_LENGTH - 1}}}$"
)
DEFAULT_COLOR = "#2962ff"
Identifier = Annotated[
    str,
    Field(pattern=IDENTIFIER_PATTERN, max_length=MAX_IDENTIFIER_LENGTH),
]
ShortText = Annotated[str, Field(max_length=100)]
WarningText = Annotated[str, Field(min_length=1, max_length=500)]
SeriesType = Literal["line", "area", "histogram"]
MarkerShape = Literal["arrowUp", "arrowDown", "circle", "square"]
MarkerPosition = Literal["aboveBar", "belowBar", "inBar"]
PriceScale = Literal["left", "right"]


class FrozenResultModel(BaseModel):
    """Reject unknown fields and attribute mutation on every result model."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PaneDefinition(FrozenResultModel):
    """One shared main pane or indicator-owned secondary pane."""

    id: Identifier
    title: ShortText
    height: int = Field(default=160, ge=40, le=1_000)
    price_scale: PriceScale = "right"


class SeriesPoint(FrozenResultModel):
    """One dated value; finiteness and alignment are checked as a collection."""

    time: date
    value: float
    color: str | None = Field(default=None, min_length=1, max_length=32)


class SeriesDefinition(FrozenResultModel):
    """A line, area, or histogram attached to one pane."""

    id: Identifier
    pane_id: Identifier
    type: SeriesType
    title: ShortText
    points: tuple[SeriesPoint, ...] = ()
    color: str = Field(default=DEFAULT_COLOR, min_length=1, max_length=32)


class MarkerDefinition(FrozenResultModel):
    """One plain-text chart marker, optionally attached to a result series."""

    time: date
    position: MarkerPosition
    shape: MarkerShape
    color: str = Field(default=DEFAULT_COLOR, min_length=1, max_length=32)
    text: str | None = Field(default=None, max_length=200)
    tooltip: str | None = Field(default=None, max_length=1_000)
    series_id: Identifier | None = None


class ReferenceLine(FrozenResultModel):
    """A horizontal price line owned by a concrete result series."""

    series_id: Identifier
    value: float
    color: str = Field(default="#8b94a7", min_length=1, max_length=32)
    title: ShortText | None = None


class IndicatorResult(FrozenResultModel):
    """Complete isolated output for one indicator calculation."""

    panes: tuple[PaneDefinition, ...] = ()
    series: tuple[SeriesDefinition, ...] = ()
    markers: tuple[MarkerDefinition, ...] = ()
    reference_lines: tuple[ReferenceLine, ...] = ()
    warnings: tuple[WarningText, ...] = ()
    error: str | None = Field(default=None, max_length=1_000)
