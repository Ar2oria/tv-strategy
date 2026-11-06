"""Provider-neutral validation for normalized daily OHLCV bars."""

import math
from collections.abc import Iterable
from datetime import date, datetime
from numbers import Rational, Real
from typing import get_args

from app.domain.dto import Adjustment, BarDTO
from app.providers.errors import ProviderDataInvalid

PRICE_FIELDS = ("open", "high", "low", "close")
VALID_ADJUSTMENTS = frozenset(get_args(Adjustment))


def validate_bars(rows: Iterable[BarDTO]) -> list[BarDTO]:
    """Return a new date-sorted list or reject the complete provider response."""
    try:
        snapshot = tuple(rows)
    except TypeError:
        raise ProviderDataInvalid("Bars must be an iterable of BarDTO values") from None
    for row in snapshot:
        _validate_bar(row)
    ordered = sorted(snapshot, key=lambda row: row.time)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.time == current.time:
            raise ProviderDataInvalid(
                f"Duplicate bar date: {current.time.isoformat()}"
            )
    return ordered


def _validate_bar(row: object) -> None:
    if not isinstance(row, BarDTO):
        raise ProviderDataInvalid("Every bar must be a BarDTO")
    if not isinstance(row.time, date) or isinstance(row.time, datetime):
        raise ProviderDataInvalid("Bar time must be a date")
    for field in PRICE_FIELDS:
        if not _is_finite_real(getattr(row, field)):
            raise ProviderDataInvalid(f"Bar {field} must be a finite number")
    if row.volume is not None:
        if not _is_finite_real(row.volume):
            raise ProviderDataInvalid("Bar volume must be a finite number or null")
        if row.volume < 0:
            raise ProviderDataInvalid("Bar volume must not be negative")
    if not (
        row.low <= row.open <= row.high
        and row.low <= row.close <= row.high
        and row.low <= row.high
    ):
        raise ProviderDataInvalid("Invalid OHLC relationship")
    if not isinstance(row.source, str) or not row.source.strip():
        raise ProviderDataInvalid("Bar source must not be blank")
    if row.adjustment not in VALID_ADJUSTMENTS:
        raise ProviderDataInvalid("Bar adjustment is not supported")


def _is_finite_real(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    if isinstance(value, Rational):
        return True
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False
