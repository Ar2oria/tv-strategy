"""Serialized BaoStock A-share and CSI300 daily OHLCV adapter."""

import logging
from datetime import date

import baostock as bs

from app.domain.dto import Adjustment, BarDTO, InstrumentDTO
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderUnavailable,
)
from app.providers.ohlcv_normalization import (
    OhlcvColumns,
    bar_from_mapping,
    parse_a_share_symbol,
    validate_fetch_range,
    validate_instrument,
)
from app.providers.sdk_runtime import provider_runtime
from app.providers.timeouts import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    validate_request_timeout,
)
from app.providers.validation import validate_bars

logger = logging.getLogger(__name__)
SOURCE = "baostock"
FULL_HISTORY_START = date(1970, 1, 1)
FIELD_NAMES = ("date", "open", "high", "low", "close", "volume", "amount")
FIELDS = ",".join(FIELD_NAMES)
COLUMNS = OhlcvColumns(
    time="date",
    open="open",
    high="high",
    low="low",
    close="close",
    volume="volume",
)
EXCHANGE_PREFIXES = {
    "SSE": "sh",
    "SH": "sh",
    "SHSE": "sh",
    "XSHG": "sh",
    "SZSE": "sz",
    "SZ": "sz",
    "XSHE": "sz",
    "BSE": "bj",
    "BJ": "bj",
}
class BaoStockOhlcvProvider:
    """Use one anonymous SDK session at a time across every provider instance."""

    def __init__(
        self,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        # BaoStock has no native query timeout; services bound cooperative waits.
        self._request_timeout_seconds = validate_request_timeout(
            request_timeout_seconds
        )

    @property
    def request_timeout_seconds(self) -> float:
        return self._request_timeout_seconds

    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        validate_instrument(instrument)
        validate_fetch_range(start, end)
        code, adjustflag = _request_spec(instrument, adjustment)
        with provider_runtime("baostock", None, wait=True):
            return _fetch_in_session(code, adjustflag, start, end, adjustment)


def _request_spec(
    instrument: InstrumentDTO,
    adjustment: Adjustment,
) -> tuple[str, str]:
    if instrument.market != "a_share":
        raise ProviderCompatibilityError("BaoStock supports A-share instruments only")
    if instrument.instrument_type == "stock":
        _require_adjustment(adjustment, "qfq", "A-share stocks")
        adjustflag = "2"
    elif instrument.instrument_type == "index":
        _require_adjustment(adjustment, "none", "A-share indices")
        adjustflag = "3"
    else:
        raise ProviderCompatibilityError("BaoStock supports stocks and CSI300 only")
    symbol = _baostock_symbol(instrument)
    if instrument.instrument_type == "index" and symbol != "sh.000300":
        raise ProviderCompatibilityError("BaoStock index fallback supports CSI300 only")
    return symbol, adjustflag


def _baostock_symbol(instrument: InstrumentDTO) -> str:
    parsed = parse_a_share_symbol(instrument.provider_symbol)
    exchange = (
        instrument.exchange.strip().upper()
        if isinstance(instrument.exchange, str)
        else ""
    )
    exchange_prefix = EXCHANGE_PREFIXES.get(exchange)
    if parsed.prefix is not None and exchange_prefix is not None:
        if parsed.prefix != exchange_prefix:
            raise ProviderDataInvalid("Provider symbol conflicts with instrument exchange")
    prefix = parsed.prefix or exchange_prefix
    if prefix is None:
        raise ProviderDataInvalid("A BaoStock exchange prefix is required")
    if prefix == "bj":
        raise ProviderCompatibilityError("BaoStock does not support Beijing instruments")
    return f"{prefix}.{parsed.code}"


def _fetch_in_session(
    code: str,
    adjustflag: str,
    start: date | None,
    end: date,
    adjustment: Adjustment,
) -> list[BarDTO]:
    _login()
    try:
        bars = _query_bars(code, adjustflag, start, end, adjustment)
    except BaseException:
        _logout_after_failure()
        raise
    _logout_after_success()
    return bars


def _login() -> None:
    try:
        result = bs.login()
    except Exception as error:
        logger.exception("BaoStock anonymous login failed")
        raise ProviderUnavailable() from error
    _ensure_success(result)


def _query_bars(
    code: str,
    adjustflag: str,
    start: date | None,
    end: date,
    adjustment: Adjustment,
) -> list[BarDTO]:
    first = start or FULL_HISTORY_START
    try:
        cursor = bs.query_history_k_data_plus(
            code,
            FIELDS,
            start_date=first.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag=adjustflag,
        )
    except Exception as error:
        logger.exception("BaoStock history query failed for %s", code)
        raise ProviderUnavailable() from error
    _ensure_success(cursor)
    return _read_cursor(cursor, adjustment)


def _read_cursor(cursor: object, adjustment: Adjustment) -> list[BarDTO]:
    bars: list[BarDTO] = []
    while _cursor_has_next(cursor):
        values = _current_row(cursor)
        row = dict(zip(FIELD_NAMES, values, strict=True))
        bars.append(
            bar_from_mapping(
                row,
                columns=COLUMNS,
                source=SOURCE,
                adjustment=adjustment,
            )
        )
    return validate_bars(bars)


def _cursor_has_next(cursor: object) -> bool:
    try:
        has_next = cursor.next()  # type: ignore[attr-defined]
    except Exception as error:
        logger.exception("BaoStock cursor iteration failed")
        raise ProviderUnavailable() from error
    _ensure_success(cursor)
    if not isinstance(has_next, bool):
        raise ProviderDataInvalid("BaoStock cursor next() must return a boolean")
    return has_next


def _current_row(cursor: object) -> list[object] | tuple[object, ...]:
    try:
        values = cursor.get_row_data()  # type: ignore[attr-defined]
    except Exception as error:
        logger.exception("BaoStock cursor row retrieval failed")
        raise ProviderUnavailable() from error
    _ensure_success(cursor)
    if not isinstance(values, (list, tuple)) or len(values) != len(FIELD_NAMES):
        raise ProviderDataInvalid("BaoStock cursor returned a malformed row")
    return values


def _ensure_success(result: object) -> None:
    error_code = getattr(result, "error_code", None)
    if error_code != "0":
        logger.error("BaoStock SDK returned error code %s", error_code)
        raise ProviderUnavailable()


def _logout_after_success() -> None:
    try:
        result = bs.logout()
    except Exception as error:
        logger.exception("BaoStock logout failed")
        raise ProviderUnavailable() from error
    _ensure_success(result)


def _logout_after_failure() -> None:
    try:
        result = bs.logout()
    except Exception:
        logger.exception("BaoStock logout failed while handling another error")
        return
    error_code = getattr(result, "error_code", None)
    if error_code != "0":
        logger.error(
            "BaoStock logout returned error code %s while handling another error",
            error_code,
        )


def _require_adjustment(
    actual: Adjustment,
    expected: Adjustment,
    instrument_description: str,
) -> None:
    if actual != expected:
        raise ProviderCompatibilityError(
            f"{instrument_description} require adjustment={expected}"
        )
