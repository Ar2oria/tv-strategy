"""Indicator protocol and immutable calculation inputs."""

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.dto import BarDTO, Timeframe
from app.indicators.models import IndicatorResult


class FrozenInputModel(BaseModel):
    """Base for validated inputs that cannot be changed by calculations."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class IndicatorParams(FrozenInputModel):
    """Base parameter model for indicators without custom parameters."""


class IndicatorContext(FrozenInputModel):
    """Instrument and requested range shared by all indicator implementations."""

    symbol: str = Field(min_length=1, max_length=64)
    timeframe: Timeframe = "1d"
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "IndicatorContext":
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("Indicator context start must not be after end")
        return self


ParamsT = TypeVar("ParamsT", bound=BaseModel)


class IndicatorInputError(ValueError):
    """An indicator received invalid bars or an invalid parameter instance."""


class Indicator(ABC):
    """Single synchronous calculation entry point implemented by every indicator."""

    name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    params_model: ClassVar[type[BaseModel]] = IndicatorParams

    @abstractmethod
    def calculate(
        self,
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        params: BaseModel,
    ) -> IndicatorResult:
        """Return a new result without modifying context, bars, or params."""


def require_params(params: BaseModel, expected: type[ParamsT]) -> ParamsT:
    """Reject accidentally unvalidated parameters at the calculation boundary."""
    if not isinstance(params, expected):
        raise IndicatorInputError(
            f"Expected {expected.__name__}, received {type(params).__name__}"
        )
    return params


def snapshot_bars(bars: Sequence[BarDTO]) -> tuple[BarDTO, ...]:
    """Detach the sequence boundary and reject invalid or non-finite market data."""
    snapshot = tuple(bars)
    previous_date: date | None = None
    for index, bar in enumerate(snapshot):
        if not isinstance(bar, BarDTO):
            raise IndicatorInputError(
                f"Bar at index {index} must be BarDTO, received {type(bar).__name__}"
            )
        if previous_date is not None and bar.time <= previous_date:
            raise IndicatorInputError("Bar dates must be strictly increasing")
        previous_date = bar.time
        for field_name in ("open", "high", "low", "close"):
            value = getattr(bar, field_name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise IndicatorInputError(
                    f"Bar {bar.time.isoformat()} has non-finite {field_name}"
                )
        if bar.high < bar.low:
            raise IndicatorInputError(
                f"Bar {bar.time.isoformat()} has high below low"
            )
    return snapshot
