"""Structural contracts implemented by concrete market-data adapters."""

from datetime import date
from typing import Protocol, runtime_checkable

from app.domain.dto import Adjustment, BarDTO, InstrumentDTO, UniverseSnapshot


@runtime_checkable
class OhlcvProvider(Protocol):
    """Synchronous source of normalized daily bars for one instrument."""

    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        """Fetch a requested range; orchestration supplies a worker thread."""
        ...


@runtime_checkable
class UniverseProvider(Protocol):
    """Synchronous source of one current universe snapshot."""

    def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
        """Fetch current membership without claiming historical composition."""
        ...
