"""Strict, provider-neutral normalization helpers for SDK OHLCV responses."""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import pandas as pd

from app.domain.dto import Adjustment, BarDTO, InstrumentDTO
from app.providers.errors import ProviderDataInvalid


@dataclass(frozen=True, slots=True)
class OhlcvColumns:
    """Explicit upstream names for one normalized bar."""

    time: str
    open: str
    high: str
    low: str
    close: str
    volume: str | None

    @property
    def required_names(self) -> tuple[str, ...]:
        names = (self.time, self.open, self.high, self.low, self.close)
        return names if self.volume is None else (*names, self.volume)


@dataclass(frozen=True, slots=True)
class ExchangeSymbol:
    """A validated numeric A-share code and optional exchange prefix."""

    code: str
    prefix: Literal["sh", "sz", "bj"] | None = None


def validate_fetch_range(start: date | None, end: date) -> None:
    """Reject invalid request dates before any provider session or request."""
    if not isinstance(end, date) or isinstance(end, datetime):
        raise ProviderDataInvalid("Fetch end must be a date")
    if start is not None and (
        not isinstance(start, date) or isinstance(start, datetime)
    ):
        raise ProviderDataInvalid("Fetch start must be a date or null")
    if start is not None and start > end:
        raise ProviderDataInvalid("Fetch start must not be after end")


def validate_instrument(instrument: InstrumentDTO) -> None:
    """Keep arbitrary objects away from provider-specific symbol handling."""
    if not isinstance(instrument, InstrumentDTO):
        raise ProviderDataInvalid("Instrument must be an InstrumentDTO")


def records_from_frame(
    frame: object,
    *,
    expected_columns: Iterable[str] | None = None,
) -> list[Mapping[str, object]]:
    """Snapshot DataFrame rows without treating malformed rows as empty data."""
    if not isinstance(frame, pd.DataFrame):
        raise ProviderDataInvalid("AKShare response must be a DataFrame")
    if len(frame.index) == 0:
        if len(frame.columns) == 0:
            return []
        if expected_columns is not None:
            required = tuple(expected_columns)
            if not frame.columns.is_unique or any(
                column not in frame.columns for column in required
            ):
                raise ProviderDataInvalid(
                    "AKShare empty response has missing or duplicate columns"
                )
        return []
    try:
        records = frame.to_dict(orient="records")
    except Exception as error:
        raise ProviderDataInvalid("Could not read AKShare response rows") from error
    if not isinstance(records, list):
        raise ProviderDataInvalid("AKShare rows must be mappings")
    return records


def bar_from_mapping(
    row: object,
    *,
    columns: OhlcvColumns,
    source: str,
    adjustment: Adjustment,
    volume_multiplier: int = 1,
) -> BarDTO:
    """Create one immutable DTO, rejecting every missing/non-finite value."""
    if not isinstance(row, Mapping):
        raise ProviderDataInvalid("Provider row must be a mapping")
    values = {name: _required_value(row, name) for name in _required_names(columns)}
    volume = (
        None
        if columns.volume is None
        else finite_number(values[columns.volume], columns.volume)
        * volume_multiplier
    )
    return BarDTO(
        time=normalize_date(values[columns.time]),
        open=finite_number(values[columns.open], columns.open),
        high=finite_number(values[columns.high], columns.high),
        low=finite_number(values[columns.low], columns.low),
        close=finite_number(values[columns.close], columns.close),
        volume=volume,
        source=source,
        adjustment=adjustment,
    )


def normalize_date(value: object) -> date:
    """Normalize SDK date/datetime values and ISO date strings."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ProviderDataInvalid("Provider bar date is invalid")


def finite_number(value: object, field: str) -> float:
    """Convert numeric SDK text to a finite float without accepting booleans."""
    if isinstance(value, bool) or value is None:
        raise ProviderDataInvalid(f"Provider {field} must be a finite number")
    if isinstance(value, str) and not value.strip():
        raise ProviderDataInvalid(f"Provider {field} must be a finite number")
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        raise ProviderDataInvalid(
            f"Provider {field} must be a finite number"
        ) from None
    if not math.isfinite(converted):
        raise ProviderDataInvalid(f"Provider {field} must be a finite number")
    return converted


def parse_a_share_symbol(value: object) -> ExchangeSymbol:
    """Parse only exact plain, prefixed, or suffixed six-digit symbols."""
    if not isinstance(value, str):
        raise ProviderDataInvalid("A-share provider symbol is invalid")
    normalized = value.strip().lower()
    patterns = (
        r"(?P<code>\d{6})",
        r"(?P<prefix>sh|sz|bj)\.?(?P<code>\d{6})",
        r"(?P<code>\d{6})\.(?P<prefix>sh|sz|bj)",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, normalized)
        if match is not None:
            prefix = match.groupdict().get("prefix")
            return ExchangeSymbol(code=match.group("code"), prefix=prefix)
    raise ProviderDataInvalid("A-share provider symbol is invalid")


def normalize_hk_stock_symbol(value: object) -> str:
    """Convert four/five-digit HK or Yahoo-style codes to AKShare's five digits."""
    if not isinstance(value, str):
        raise ProviderDataInvalid("Hong Kong provider symbol is invalid")
    normalized = value.strip().upper()
    if normalized.endswith(".HK"):
        normalized = normalized[:-3]
    if re.fullmatch(r"\d{4,5}", normalized) is None:
        raise ProviderDataInvalid("Hong Kong provider symbol is invalid")
    return normalized.zfill(5)


def _required_names(columns: OhlcvColumns) -> tuple[str, ...]:
    return columns.required_names


def _required_value(row: Mapping[str, object], name: str) -> object:
    try:
        return row[name]
    except KeyError:
        raise ProviderDataInvalid(f"Provider row is missing {name}") from None
