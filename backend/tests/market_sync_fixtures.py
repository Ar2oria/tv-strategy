"""Offline fixtures shared by market synchronization tests."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.domain.dto import Adjustment, BarDTO, InstrumentDTO
from app.services.bar_sync_service import BarSyncOptions

TODAY = date(2026, 1, 31)


@dataclass(frozen=True, slots=True)
class FetchCall:
    instrument: InstrumentDTO
    start: date | None
    end: date
    adjustment: Adjustment


class ScriptedProvider:
    """Return queued responses while recording synchronous provider calls."""

    def __init__(self, *responses: object) -> None:
        self._responses = iter(responses)
        self.calls: list[FetchCall] = []

    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        self.calls.append(FetchCall(instrument, start, end, adjustment))
        response = next(self._responses, [])
        if isinstance(response, Exception):
            raise response
        if not isinstance(response, list):
            raise TypeError("Scripted provider responses must be lists or exceptions")
        return response


def instrument_dto(
    symbol: str = "AAA",
    *,
    market: Literal["a_share", "hk_stock", "us_stock", "crypto"] = "us_stock",
    instrument_type: Literal["stock", "index", "etf", "crypto_spot"] = "stock",
    exchange: str = "NASDAQ",
) -> InstrumentDTO:
    currency = "USD" if market == "us_stock" else "HKD"
    timezone = "America/New_York" if market == "us_stock" else "Asia/Hong_Kong"
    return InstrumentDTO(
        symbol=symbol,
        name=symbol,
        market=market,
        exchange=exchange,
        currency=currency,
        timezone=timezone,
        instrument_type=instrument_type,
        provider_symbol=symbol,
    )


def bar(
    day: date,
    *,
    source: str = "yfinance",
    adjustment: Adjustment = "qfq",
    open: float = 10.0,
    high: float = 12.0,
    low: float = 9.0,
    close: float = 11.0,
    volume: float | None = 100.0,
) -> BarDTO:
    return BarDTO(
        time=day,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=source,
        adjustment=adjustment,
    )


def market_config(**changes: object) -> BarSyncOptions:
    values: dict[str, object] = {
        "provider": "yfinance",
        "history_years": 2,
        "overlap_days": 5,
        "adjustment": "auto",
    }
    values.update(changes)
    return BarSyncOptions(**values)  # type: ignore[arg-type]
