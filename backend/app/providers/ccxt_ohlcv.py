"""Bounded divide-and-conquer Binance and OKX spot OHLCV discovery."""

import logging
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Literal

import ccxt

from app.domain.dto import Adjustment, BarDTO, InstrumentDTO
from app.providers.crypto_catalog import parse_spot_pair
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderConfigurationError,
    ProviderDataInvalid,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.ohlcv_normalization import (
    finite_number,
    validate_fetch_range,
    validate_instrument,
)
from app.providers.retry import retry_after_from_error
from app.providers.timeouts import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    validate_request_timeout,
)
from app.providers.validation import validate_bars

logger = logging.getLogger(__name__)
ExchangeId = Literal["binance", "okx"]
UTC = timezone.utc
DAY_MS = 86_400_000
FULL_HISTORY_START = date(1970, 1, 1)
MAX_PAGES = 1000
PAGE_LIMITS = MappingProxyType({"binance": 1000, "okx": 100})
_RATE_LIMIT_STATUSES = frozenset({418, 429})
_HTTP_STATUS_PATTERN = re.compile(
    r"\b(?:HTTP(?:/\d(?:\.\d)?)?(?:\s+status)?|status(?:[ _]code)?)"
    r"(?:\s*[:=]\s*|\s+)(?P<status>\d{3})(?![\w.])",
    re.IGNORECASE,
)


class CcxtOhlcvProvider:
    """Own one explicitly configured SDK session per complete fetch."""

    def __init__(
        self,
        exchange_id: ExchangeId,
        clock: Callable[..., datetime] | None = None,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        proxy_url: str | None = None,
    ) -> None:
        if not isinstance(exchange_id, str) or exchange_id not in PAGE_LIMITS:
            raise ProviderConfigurationError("Unsupported CCXT exchange")
        if clock is not None and not callable(clock):
            raise ProviderConfigurationError("CCXT clock must be callable")
        self._exchange_id: ExchangeId = exchange_id
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
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
        self._validate_instrument(instrument, adjustment)
        current_day = _current_utc_day(self._clock)
        first = start or FULL_HISTORY_START
        try:
            last_complete_day = current_day - timedelta(days=1)
        except OverflowError:
            return []
        effective_end = min(end, last_complete_day)
        if first > effective_end:
            return []

        exchange = self._create_exchange()
        failure_active = False
        try:
            return self._download(
                exchange,
                instrument.provider_symbol,
                first,
                effective_end,
            )
        except BaseException:
            failure_active = True
            raise
        finally:
            self._close_exchange(exchange, failure_active)

    def _validate_instrument(
        self, instrument: InstrumentDTO, adjustment: Adjustment
    ) -> None:
        if adjustment != "none":
            raise ProviderCompatibilityError("Crypto spot bars require adjustment=none")
        if instrument.market != "crypto" or instrument.instrument_type != "crypto_spot":
            raise ProviderCompatibilityError("CCXT adapter supports crypto spot only")
        if instrument.exchange != self._exchange_id:
            raise ProviderCompatibilityError("Instrument exchange does not match CCXT adapter")
        parse_spot_pair(instrument.provider_symbol)
        expected_symbol = f"{self._exchange_id.upper()}:{instrument.provider_symbol}"
        if instrument.symbol != expected_symbol:
            raise ProviderDataInvalid("Crypto instrument symbol is not canonical")

    def _create_exchange(self) -> object:
        timeout_ms = max(1, int(round(self._request_timeout_seconds * 1000)))
        try:
            constructor = getattr(ccxt, self._exchange_id)
            config: dict[str, object] = {
                "enableRateLimit": True,
                "timeout": timeout_ms,
                "requests_trust_env": False,
            }
            if self._proxy_url is not None:
                config = {
                    **config,
                    "proxies": {"http": self._proxy_url, "https": self._proxy_url},
                }
            if self._exchange_id == "binance":
                config = {**config, "options": {"fetchMarkets": ["spot"]}}
            return constructor(config)
        except Exception as error:
            logger.warning("CCXT %s construction failed", self._exchange_id)
            raise _provider_failure(
                error, exchange_id=self._exchange_id, operation="exchange construction"
            ) from error

    def _download(
        self,
        exchange: object,
        symbol: str,
        start: date,
        end: date,
    ) -> list[BarDTO]:
        limit = PAGE_LIMITS[self._exchange_id]
        pending = [(_utc_day_ms(start), _utc_day_ms(end) + DAY_MS - 1)]
        pages: tuple[tuple[BarDTO, ...], ...] = ()
        seen_dates: frozenset[date] = frozenset()
        seen_signatures: frozenset[tuple[int, ...]] = frozenset()
        request_count = 0
        while pending:
            if request_count >= MAX_PAGES:
                raise ProviderUnavailable(
                    detail="CCXT pagination page limit exceeded"
                )
            interval_start, interval_end = pending.pop()
            rows = _page_rows(
                self._request_page(
                    exchange,
                    symbol,
                    since=interval_start,
                    until=interval_end,
                    limit=limit,
                )
            )
            request_count += 1
            if not rows:
                pending.extend(_empty_subintervals(interval_start, interval_end, limit))
                continue

            parsed = tuple(_parse_row(row, self._exchange_id) for row in rows)
            timestamps = tuple(timestamp for timestamp, _ in parsed)
            signature = tuple(sorted(timestamps))
            if signature in seen_signatures:
                raise ProviderDataInvalid("CCXT repeated pagination window")
            page_bars = tuple(bar for _, bar in parsed)
            validate_bars(page_bars)
            page_dates = frozenset(bar.time for bar in page_bars)
            if seen_dates & page_dates:
                raise ProviderDataInvalid("Duplicate bar date across CCXT windows")
            if any(
                timestamp < interval_start or timestamp > interval_end
                for timestamp in timestamps
            ):
                raise ProviderDataInvalid(
                    "CCXT non-advancing pagination window: "
                    "row is outside the requested window"
                )
            if any(
                current <= previous
                for previous, current in zip(timestamps, timestamps[1:], strict=False)
            ):
                raise ProviderDataInvalid("CCXT rows must be strictly ordered")

            pages = (*pages, page_bars)
            seen_dates = seen_dates | page_dates
            seen_signatures = seen_signatures | {signature}
            pending.extend(
                _missing_subintervals(
                    interval_start,
                    interval_end,
                    oldest=timestamps[0],
                    latest=timestamps[-1],
                )
            )
        return validate_bars(bar for page in pages for bar in page)

    def _request_page(
        self,
        exchange: object,
        symbol: str,
        *,
        since: int,
        until: int,
        limit: int,
    ) -> object:
        params = {"until": until}
        if self._exchange_id == "okx":
            params["type"] = "HistoryCandles"
        try:
            return exchange.fetch_ohlcv(  # type: ignore[attr-defined]
                symbol,
                timeframe="1d",
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as error:
            logger.warning("CCXT %s OHLCV request failed", self._exchange_id)
            raise _provider_failure(
                error, exchange_id=self._exchange_id, operation="OHLCV request"
            ) from error

    def _close_exchange(self, exchange: object, failure_active: bool) -> None:
        try:
            close = getattr(exchange, "close", None)
            if callable(close):
                close()
            else:
                exchange.session.close()  # type: ignore[attr-defined]
        except Exception as error:
            logger.warning("CCXT %s close failed", self._exchange_id)
            if not failure_active:
                raise _provider_failure(
                    error, exchange_id=self._exchange_id, operation="exchange cleanup"
                ) from error


def _missing_subintervals(
    start: int,
    end: int,
    *,
    oldest: int,
    latest: int,
) -> tuple[tuple[int, int], ...]:
    """Return uncovered left/right intervals; the right side is processed first."""
    intervals: tuple[tuple[int, int], ...] = ()
    if oldest > start:
        previous_end = oldest - 1
        if previous_end < start:
            raise ProviderDataInvalid("CCXT non-advancing pagination window")
        intervals = ((start, previous_end),)
    latest_day_end = _utc_day_ms(_utc_date(latest)) + DAY_MS - 1
    if latest_day_end < end:
        next_start = latest + 1
        if next_start <= latest or next_start > end:
            raise ProviderDataInvalid("CCXT non-advancing pagination window")
        return (*intervals, (next_start, end))
    return intervals


def _empty_subintervals(
    start: int,
    end: int,
    limit: int,
) -> tuple[tuple[int, int], ...]:
    """Split empty windows beyond page capacity without repeating requests."""
    if start > end:
        raise ProviderDataInvalid("CCXT non-advancing pagination window")
    start_day = _utc_day_ms(_utc_date(start))
    end_day = _utc_day_ms(_utc_date(end))
    if start_day == end_day:
        return ()
    day_count = (end_day - start_day) // DAY_MS + 1
    if day_count <= limit:
        return ()
    left_days = limit
    left_end = min(end, start_day + left_days * DAY_MS - 1)
    right_start = left_end + 1
    if left_end < start or right_start > end:
        raise ProviderDataInvalid("CCXT non-advancing pagination window")
    return ((start, left_end), (right_start, end))


def _page_rows(page: object) -> list[object]:
    if not isinstance(page, (list, tuple)):
        raise ProviderDataInvalid("CCXT OHLCV page must be a list of rows")
    return list(page)


def _parse_row(row: object, source: ExchangeId) -> tuple[int, BarDTO]:
    if not isinstance(row, (list, tuple)) or len(row) != 6:
        raise ProviderDataInvalid("CCXT OHLCV row must contain exactly six values")
    timestamp = _timestamp_ms(row[0])
    return timestamp, BarDTO(
        time=_utc_date(timestamp),
        open=finite_number(row[1], "open"),
        high=finite_number(row[2], "high"),
        low=finite_number(row[3], "low"),
        close=finite_number(row[4], "close"),
        volume=finite_number(row[5], "volume"),
        source=source,
        adjustment="none",
    )


def _timestamp_ms(value: object) -> int:
    numeric = finite_number(value, "timestamp")
    if not numeric.is_integer():
        raise ProviderDataInvalid("CCXT timestamp must be integral UTC milliseconds")
    timestamp = int(numeric)
    _utc_date(timestamp)
    return timestamp


def _utc_date(timestamp: int) -> date:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    try:
        return (epoch + timedelta(milliseconds=timestamp)).date()
    except (OverflowError, ValueError):
        raise ProviderDataInvalid("CCXT timestamp is outside the supported UTC range") from None


def _utc_day_ms(day: date) -> int:
    return (day.toordinal() - FULL_HISTORY_START.toordinal()) * DAY_MS


def _current_utc_day(clock: Callable[..., datetime]) -> date:
    try:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        if value.utcoffset() is None:
            raise ValueError("datetime must have a UTC offset")
        return value.astimezone(UTC).date()
    except Exception as error:
        raise ProviderDataInvalid("CCXT clock must return an aware datetime") from error


def _provider_failure(
    error: Exception, *, exchange_id: ExchangeId, operation: str
) -> ProviderError:
    retry_after = retry_after_from_error(error)
    detail = f"CCXT {exchange_id} {operation} failed ({type(error).__name__})"
    if _is_rate_limited(error):
        return ProviderRateLimited(detail=detail, retry_after=retry_after)
    return ProviderUnavailable(detail=detail, retry_after=retry_after)


def _is_rate_limited(error: Exception) -> bool:
    if isinstance(error, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
        return True
    for attribute in ("http_status_code", "status_code", "status"):
        if str(getattr(error, attribute, "")) in {"418", "429"}:
            return True
    response = getattr(error, "response", None)
    if str(getattr(response, "status_code", "")) in {"418", "429"}:
        return True
    match = _HTTP_STATUS_PATTERN.search(str(error))
    return match is not None and int(match.group("status")) in _RATE_LIMIT_STATUSES
