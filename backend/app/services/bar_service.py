"""Daily bar reads with immutable ISO-week and calendar-month aggregation."""

from collections.abc import Sequence
from datetime import date

from app.domain.dto import BarDTO, InstrumentRecord, Timeframe
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository

SUPPORTED_TIMEFRAMES = frozenset({"1d", "1w", "1M"})


class InstrumentNotFoundError(LookupError):
    """The requested instrument does not exist in the local catalog."""


def aggregate_daily(
    bars: Sequence[BarDTO], timeframe: Timeframe
) -> list[BarDTO]:
    """Aggregate ascending daily bars without writing or modifying source data."""
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe!r}")
    snapshot = _validated_snapshot(bars)
    if timeframe == "1d":
        return list(snapshot)

    aggregated: list[BarDTO] = []
    group: list[BarDTO] = []
    group_key: tuple[int, int] | None = None
    for bar in snapshot:
        key = _period_key(bar.time, timeframe)
        if group_key is not None and key != group_key:
            aggregated.append(_aggregate_group(group))
            group = []
        group.append(bar)
        group_key = key
    if group:
        aggregated.append(_aggregate_group(group))
    return aggregated


class BarService:
    """Read detached bars and retain earlier history needed by aggregation."""

    def __init__(
        self, bars: BarRepository, instruments: InstrumentRepository
    ) -> None:
        self._bars = bars
        self._instruments = instruments

    def get_visible(
        self,
        instrument_id: int,
        timeframe: Timeframe = "1d",
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[BarDTO]:
        """Return inclusive visible bars, optionally retaining only the latest N."""
        self._require_instrument(instrument_id)
        _validate_range(start, end)
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        lower = start or date.min
        upper = end or date.max
        daily = self._bars.get_all_until(instrument_id, upper)
        aggregated = aggregate_daily(daily, timeframe)
        visible = [bar for bar in aggregated if lower <= bar.time <= upper]
        return visible if limit is None else visible[-limit:]

    def get_history_until(
        self,
        instrument_id: int,
        end: date | None,
        timeframe: Timeframe = "1d",
    ) -> list[BarDTO]:
        """Read all stored history through end (None means unbounded)."""
        self._require_instrument(instrument_id)
        daily = self._bars.get_all_until(instrument_id, end)
        return aggregate_daily(daily, timeframe)

    def _require_instrument(self, instrument_id: int) -> InstrumentRecord:
        instrument = self._instruments.get_by_id(instrument_id)
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument {instrument_id} does not exist"
            )
        return instrument


def _validated_snapshot(bars: Sequence[BarDTO]) -> tuple[BarDTO, ...]:
    snapshot = tuple(bars)
    previous: date | None = None
    for index, bar in enumerate(snapshot):
        if not isinstance(bar, BarDTO):
            raise TypeError(f"Bar at index {index} must be a BarDTO")
        if previous is not None and bar.time <= previous:
            raise ValueError("Bar dates must be strictly increasing")
        previous = bar.time
    return snapshot


def _period_key(day: date, timeframe: Timeframe) -> tuple[int, int]:
    if timeframe == "1w":
        iso = day.isocalendar()
        return iso.year, iso.week
    return day.year, day.month


def _aggregate_group(group: Sequence[BarDTO]) -> BarDTO:
    if not group:
        raise ValueError("Cannot aggregate an empty bar group")
    last = group[-1]
    volumes = [bar.volume for bar in group if bar.volume is not None]
    return BarDTO(
        time=last.time,
        open=group[0].open,
        high=max(bar.high for bar in group),
        low=min(bar.low for bar in group),
        close=last.close,
        volume=(
            None
            if any(bar.volume is None for bar in group)
            else sum(volumes)
        ),
        source=last.source,
        adjustment=last.adjustment,
    )


def _validate_range(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError("start must not be later than end")
