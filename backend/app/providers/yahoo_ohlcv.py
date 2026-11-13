"""Yahoo Finance OHLCV adapter with explicit US/HK symbol semantics."""

import logging
import re
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from app.domain.dto import Adjustment, BarDTO, InstrumentDTO, InstrumentType
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.ohlcv_normalization import (
    finite_number,
    normalize_date,
    validate_fetch_range,
    validate_instrument,
)
from app.providers.retry import retry_after_from_error
from app.providers.sdk_runtime import provider_runtime
from app.providers.timeouts import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    validate_request_timeout,
)
from app.providers.validation import validate_bars

logger = logging.getLogger(__name__)
SOURCE = "yfinance"
FULL_HISTORY_START = date(1900, 1, 1)
_OHLC_COLUMNS = ("Open", "High", "Low", "Close")
_HISTORY_COLUMNS = (*_OHLC_COLUMNS, "Volume")
_US_TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*")
_MAX_TICKER_LENGTH = 32


class YahooOhlcvProvider:
    """Fetch adjusted stocks/ETFs and unadjusted supported Yahoo indices."""

    def __init__(
        self,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        proxy_url: str | None = None,
    ) -> None:
        self._request_timeout_seconds = validate_request_timeout(
            request_timeout_seconds
        )
        self._proxy_url = proxy_url

    @property
    def request_timeout_seconds(self) -> float:
        return self._request_timeout_seconds

    @property
    def proxy_url(self) -> str | None:
        return self._proxy_url

    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        validate_instrument(instrument)
        validate_fetch_range(start, end)
        yahoo_symbol, expected_adjustment = _resolve_instrument(instrument)
        if adjustment != expected_adjustment:
            raise ProviderCompatibilityError(
                f"{instrument.instrument_type} requires adjustment={expected_adjustment}"
            )
        exclusive_end = _exclusive_end(end)
        frame = _request(
            yahoo_symbol,
            start=(start or FULL_HISTORY_START).isoformat(),
            end=exclusive_end.isoformat(),
            adjustment=adjustment,
            timeout=self._request_timeout_seconds,
            proxy_url=self._proxy_url,
        )
        bars = _normalize_history(
            frame,
            adjustment,
            instrument.instrument_type,
        )
        return _require_requested_range(bars, start, end)


def _resolve_instrument(instrument: InstrumentDTO) -> tuple[str, Adjustment]:
    if instrument.market == "us_stock":
        if instrument.instrument_type in {"stock", "etf"}:
            return _us_yahoo_symbol(instrument.provider_symbol), "qfq"
        if instrument.instrument_type == "index":
            symbol = _index_symbol(instrument.provider_symbol)
            if symbol != "^NDX":
                raise ProviderCompatibilityError("Yahoo US adapter supports ^NDX only")
            return symbol, "none"
    elif instrument.market == "hk_stock":
        if instrument.instrument_type == "stock":
            return _hk_yahoo_symbol(instrument.provider_symbol), "qfq"
        if instrument.instrument_type == "index":
            symbol = _index_symbol(instrument.provider_symbol)
            if symbol not in {"HSTECH", "HSTECH.HK"}:
                raise ProviderCompatibilityError(
                    "Yahoo HK adapter supports HSTECH.HK only"
                )
            return "HSTECH.HK", "none"
    else:
        raise ProviderCompatibilityError("Yahoo adapter supports US and HK markets only")
    raise ProviderCompatibilityError("Yahoo adapter does not support this instrument type")


def _index_symbol(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderDataInvalid("Yahoo index provider symbol is invalid")
    return value.strip().upper()


def _us_yahoo_symbol(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderDataInvalid("US provider symbol is invalid")
    normalized = value.strip().upper()
    if (
        len(normalized) > _MAX_TICKER_LENGTH
        or _US_TICKER_PATTERN.fullmatch(normalized) is None
    ):
        raise ProviderDataInvalid("US provider symbol is invalid")
    return normalized.replace(".", "-").replace("/", "-")


def _hk_yahoo_symbol(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderDataInvalid("Hong Kong provider symbol is invalid")
    normalized = value.strip().upper()
    if normalized.endswith(".HK"):
        normalized = normalized[:-3]
    if re.fullmatch(r"\d{1,5}", normalized) is None:
        raise ProviderDataInvalid("Hong Kong provider symbol is invalid")
    if len(normalized) < 4:
        normalized = normalized.zfill(4)
    elif len(normalized) == 5 and normalized.startswith("0"):
        normalized = normalized[1:]
    return f"{normalized}.HK"


def _exclusive_end(end: date) -> date:
    try:
        return end + timedelta(days=1)
    except OverflowError:
        raise ProviderDataInvalid("Fetch end is too large for Yahoo") from None


def _request(
    symbol: str,
    *,
    start: str,
    end: str,
    adjustment: Adjustment,
    timeout: float,
    proxy_url: str | None = None,
) -> object:
    try:
        with provider_runtime("yfinance", proxy_url, wait=True):
            return yf.Ticker(symbol).history(
                interval="1d",
                start=start,
                end=end,
                auto_adjust=adjustment == "qfq",
                timeout=timeout,
            )
    except YFRateLimitError as error:
        logger.warning("Yahoo rate limit for %s", symbol)
        raise ProviderRateLimited(
            retry_after=retry_after_from_error(error)
        ) from error
    except Exception as error:
        logger.warning("Yahoo request failed for %s (%s)", symbol, type(error).__name__)
        raise ProviderUnavailable() from error


def _normalize_history(
    frame: object,
    adjustment: Adjustment,
    instrument_type: InstrumentType,
) -> list[BarDTO]:
    if not isinstance(frame, pd.DataFrame):
        raise ProviderDataInvalid("Yahoo response must be a DataFrame")
    if frame.empty and len(frame.columns) == 0:
        return []
    required = (
        _OHLC_COLUMNS
        if instrument_type == "index"
        else _HISTORY_COLUMNS
    )
    if not frame.columns.is_unique or any(
        column not in frame.columns for column in required
    ):
        raise ProviderDataInvalid("Yahoo response is missing OHLCV columns")
    if frame.empty:
        return []
    bars = [
        _bar_from_row(
            timestamp,
            row,
            adjustment,
            is_index=instrument_type == "index",
        )
        for timestamp, row in frame.iterrows()
    ]
    return validate_bars(bars)


def _bar_from_row(
    timestamp: object,
    row: pd.Series,
    adjustment: Adjustment,
    *,
    is_index: bool,
) -> BarDTO:
    return BarDTO(
        time=_history_date(timestamp),
        open=finite_number(row["Open"], "Open"),
        high=finite_number(row["High"], "High"),
        low=finite_number(row["Low"], "Low"),
        close=finite_number(row["Close"], "Close"),
        volume=(
            _index_volume(row.get("Volume"))
            if is_index
            else finite_number(row["Volume"], "Volume")
        ),
        source=SOURCE,
        adjustment=adjustment,
    )


def _index_volume(value: object) -> float | None:
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = False
    if missing:
        return None
    numeric = finite_number(value, "Volume")
    return None if numeric == 0 else numeric


def _require_requested_range(
    bars: list[BarDTO],
    start: date | None,
    end: date,
) -> list[BarDTO]:
    if any(
        (start is not None and bar.time < start) or bar.time > end
        for bar in bars
    ):
        raise ProviderDataInvalid("Yahoo bars are outside the requested range")
    return bars


def _history_date(value: object) -> date:
    if isinstance(value, (date, datetime)):
        return normalize_date(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    raise ProviderDataInvalid("Yahoo bar date is invalid")
