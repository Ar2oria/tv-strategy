"""AKShare OHLCV adapter with A-share lots normalized to share volume."""

import logging
from collections.abc import Callable
from datetime import date

import akshare as ak
from akshare.utils.http import Push2RateLimitError

from app.domain.dto import Adjustment, BarDTO, InstrumentDTO
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.ohlcv_normalization import (
    OhlcvColumns,
    bar_from_mapping,
    normalize_hk_stock_symbol,
    parse_a_share_symbol,
    records_from_frame,
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
SOURCE = "akshare"
PUSH2_RATE_LIMIT_DETAIL = (
    "Eastmoney push2 rate limit exceeded, wait before resuming synchronization"
)
SHARES_PER_LOT = 100
FULL_HISTORY_START = date(1970, 1, 1)
CHINESE_COLUMNS = OhlcvColumns(
    time="日期",
    open="开盘",
    high="最高",
    low="最低",
    close="收盘",
    volume="成交量",
)
HSTECH_COLUMNS = OhlcvColumns(
    time="date",
    open="open",
    high="high",
    low="low",
    close="latest",
    volume=None,
)


class AkshareOhlcvProvider:
    """Translate documented AKShare responses into validated immutable bars."""

    def __init__(
        self,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        proxy_url: str | None = None,
    ) -> None:
        # AKShare has no common native timeout argument; services bound waiting.
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
        if instrument.market == "a_share":
            bars = self._fetch_a_share(instrument, start, end, adjustment)
        elif instrument.market == "hk_stock":
            bars = self._fetch_hk(instrument, start, end, adjustment)
        else:
            raise ProviderCompatibilityError("AKShare does not support this market")
        if any(
            (start is not None and bar.time < start) or bar.time > end
            for bar in bars
        ):
            raise ProviderDataInvalid("AKShare bars are outside the requested range")
        return bars

    def _fetch_a_share(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        symbol = parse_a_share_symbol(instrument.provider_symbol).code
        dates = _akshare_dates(start, end)
        if instrument.instrument_type == "stock":
            _require_adjustment(adjustment, "qfq", "A-share stocks")
            frame = _request(
                ak.stock_zh_a_hist,
                proxy_url=self._proxy_url,
                symbol=symbol,
                period="daily",
                start_date=dates[0],
                end_date=dates[1],
                adjust="qfq",
            )
        elif instrument.instrument_type == "index":
            _require_adjustment(adjustment, "none", "A-share indices")
            frame = _request(
                ak.index_zh_a_hist,
                proxy_url=self._proxy_url,
                symbol=symbol,
                period="daily",
                start_date=dates[0],
                end_date=dates[1],
            )
        else:
            raise ProviderCompatibilityError(
                "AKShare A-share adapter supports stocks and indices only"
            )
        return _normalize_frame(
            frame,
            CHINESE_COLUMNS,
            adjustment,
            volume_multiplier=SHARES_PER_LOT,
        )

    def _fetch_hk(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        if instrument.instrument_type == "stock":
            _require_adjustment(adjustment, "qfq", "Hong Kong stocks")
            dates = _akshare_dates(start, end)
            frame = _request(
                ak.stock_hk_hist,
                proxy_url=self._proxy_url,
                symbol=normalize_hk_stock_symbol(instrument.provider_symbol),
                period="daily",
                start_date=dates[0],
                end_date=dates[1],
                adjust="qfq",
            )
            return _normalize_frame(frame, CHINESE_COLUMNS, adjustment)
        if instrument.instrument_type != "index":
            raise ProviderCompatibilityError(
                "AKShare Hong Kong adapter supports stocks and HSTECH only"
            )
        _require_adjustment(adjustment, "none", "Hong Kong indices")
        _require_hstech(instrument.provider_symbol)
        frame = _request(
            ak.stock_hk_index_daily_em,
            proxy_url=self._proxy_url,
            symbol="HSTECH",
        )
        return _normalize_frame(frame, HSTECH_COLUMNS, adjustment)


def _normalize_frame(
    frame: object,
    columns: OhlcvColumns,
    adjustment: Adjustment,
    volume_multiplier: int = 1,
) -> list[BarDTO]:
    records = records_from_frame(frame, expected_columns=columns.required_names)
    bars = [
        bar_from_mapping(
            row,
            columns=columns,
            source=SOURCE,
            adjustment=adjustment,
            volume_multiplier=volume_multiplier,
        )
        for row in records
    ]
    return validate_bars(bars)


def _request(
    function: Callable[..., object],
    *,
    proxy_url: str | None = None,
    **kwargs: object,
) -> object:
    try:
        with provider_runtime("akshare", proxy_url, wait=True):
            return function(**kwargs)
    except Push2RateLimitError as error:
        logger.warning("AKShare Eastmoney push2 rate limit")
        raise ProviderRateLimited(detail=PUSH2_RATE_LIMIT_DETAIL) from error
    except Exception as error:
        logger.error(
            "AKShare request failed for symbol %s (%s)",
            kwargs.get("symbol"),
            type(error).__name__,
        )
        detail = f"AKShare daily request failed ({type(error).__name__})"
        raise ProviderUnavailable(detail=detail) from error


def _akshare_dates(start: date | None, end: date) -> tuple[str, str]:
    first = start or FULL_HISTORY_START
    return first.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _require_adjustment(
    actual: Adjustment,
    expected: Adjustment,
    instrument_description: str,
) -> None:
    if actual != expected:
        raise ProviderCompatibilityError(
            f"{instrument_description} require adjustment={expected}"
        )


def _require_hstech(provider_symbol: object) -> None:
    if not isinstance(provider_symbol, str):
        raise ProviderCompatibilityError("Only HSTECH is supported for HK indices")
    if provider_symbol.strip().upper() not in {"HSTECH", "HSTECH.HK"}:
        raise ProviderCompatibilityError("Only HSTECH is supported for HK indices")
