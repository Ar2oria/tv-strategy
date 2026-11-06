"""Immutable data-transfer objects shared by providers and repositories."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

Market = Literal["a_share", "hk_stock", "us_stock", "crypto"]
InstrumentType = Literal["stock", "index", "etf", "crypto_spot"]
Adjustment = Literal["qfq", "none"]
Timeframe = Literal["1d", "1w", "1M"]
TriggerType = Literal["manual", "scheduled"]
TaskStatus = Literal[
    "queued",
    "running",
    "success",
    "partial",
    "failed",
    "skipped",
    "interrupted",
]


@dataclass(frozen=True, slots=True)
class InstrumentDTO:
    """Canonical provider-neutral instrument metadata."""

    symbol: str
    name: str
    market: Market
    exchange: str
    currency: str
    timezone: str
    instrument_type: InstrumentType
    provider_symbol: str


@dataclass(frozen=True, slots=True)
class InstrumentRecord(InstrumentDTO):
    """Instrument metadata with its stable database identity."""

    id: int
    active: bool


@dataclass(frozen=True, slots=True)
class BarDTO:
    """One normalized daily OHLCV bar."""

    time: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source: str
    adjustment: Adjustment


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    """A current universe plus non-constituent index/ETF instruments."""

    universe_code: str
    source: str
    effective_date: date | None
    members: tuple[InstrumentDTO, ...]
    related_instruments: tuple[InstrumentDTO, ...] = ()

    def __post_init__(self) -> None:
        """Detach tuple boundaries even when callers supply sequences."""
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(
            self, "related_instruments", tuple(self.related_instruments)
        )


@dataclass(frozen=True, slots=True)
class TaskRunDTO:
    """Detached task execution state."""

    id: int
    task_name: str
    trigger: TriggerType
    status: TaskStatus
    params: dict[str, Any]
    config_snapshot: dict[str, Any] | None
    progress: float
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class TaskLogDTO:
    """One structured task log entry."""

    id: int
    run_id: int
    level: str
    message: str
    context: dict[str, Any]
    created_at: datetime
