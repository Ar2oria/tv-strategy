"""Frozen and strictly validated read API input models."""

from datetime import date
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.domain.dto import Market, Timeframe
from app.indicators.models import Identifier

INSTANCE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
DEFAULT_BAR_LIMIT = 5_000
MAX_BAR_LIMIT = 50_000
MAX_SEARCH_LIMIT = 100
MAX_SEARCH_OFFSET = 100_000


class FrozenAPIInput(BaseModel):
    """Reject unknown fields and prevent attribute mutation on all inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DateRangeInput(FrozenAPIInput):
    """Shared inclusive date-range invariant."""

    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> Self:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start must not be later than end")
        return self


class BarsQuery(DateRangeInput):
    """Validated query parameters for daily, weekly, or monthly bars."""

    instrument_id: int = Field(gt=0)
    timeframe: Timeframe = "1d"
    limit: int = Field(default=DEFAULT_BAR_LIMIT, ge=1, le=MAX_BAR_LIMIT)


class InstrumentsQuery(FrozenAPIInput):
    """Bounded active-instrument filters and pagination."""

    query: str | None = Field(default=None, max_length=100)
    market: Market | None = None
    universe_code: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=50, ge=1, le=MAX_SEARCH_LIMIT)
    offset: int = Field(default=0, ge=0, le=MAX_SEARCH_OFFSET)

    @field_validator("query", "universe_code")
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Optional search text must not be blank")
        return value


class IndicatorInstanceRequest(FrozenAPIInput):
    """One independently named and parameterized indicator instance."""

    instance_id: str = Field(pattern=INSTANCE_ID_PATTERN, max_length=64)
    name: Identifier
    params: dict[str, JsonValue] = Field(default_factory=dict)


class IndicatorComputeRequest(FrozenAPIInput):
    """One batch sharing an instrument, timeframe, and visible date range."""

    instrument_id: int = Field(gt=0)
    timeframe: Timeframe = "1d"
    start: date | None = None
    end: date | None = None
    limit: int | None = Field(default=None, ge=1, le=MAX_BAR_LIMIT)
    indicators: tuple[IndicatorInstanceRequest, ...] = ()

    @model_validator(mode="after")
    def batch_is_consistent(self) -> Self:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start must not be later than end")
        instance_ids = [item.instance_id for item in self.indicators]
        if len(set(instance_ids)) != len(instance_ids):
            raise ValueError("Indicator instance_id values must be unique")
        return self
