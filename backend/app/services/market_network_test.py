"""Bounded, non-persisting latest-price checks through saved providers."""

import logging
import math
import re
import time
from collections.abc import Callable
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field

from app.config.models import CryptoSymbol
from app.domain.dto import Adjustment, InstrumentDTO, Market
from app.providers.base import OhlcvProvider
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import ProviderBusy, ProviderDataInvalid, ProviderError
from app.providers.ohlcv_normalization import (
    normalize_hk_stock_symbol,
    parse_a_share_symbol,
)
from app.providers.registry import ProviderRegistry
from app.providers.sdk_runtime import provider_busy, provider_runtime
from app.services.provider_calls import call_provider_sync

logger = logging.getLogger(__name__)
NETWORK_TEST_LOOKBACK_DAYS = 31
EMPTY_PRICE_DETAIL = "No market data is available for the requested symbol"
UNEXPECTED_TEST_ERROR = "Network test failed"
_US_SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*")
_A_PREFIXES = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "30"),
    "bj": ("4", "8", "920"),
}
_A_EXCHANGES = {"sh": "SSE", "sz": "SZSE", "bj": "BSE"}


class NetworkTestInputError(ValueError):
    """The submitted symbol is invalid for the selected market."""

    def __init__(self) -> None:
        super().__init__("Invalid symbol for this market")


class NetworkTestResult(BaseModel):
    """Immutable public result of one bounded provider probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: Market
    provider: str
    symbol: str
    connected: bool
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    price: float | None = Field(default=None, allow_inf_nan=False)
    price_date: date | None = None
    currency: str | None = None
    error_type: str | None = None
    detail: str | None = None


class MarketNetworkTestService:
    """Run one real daily-bar probe without touching persistent application state."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        if not isinstance(registry, ProviderRegistry):
            raise TypeError("registry must be a ProviderRegistry")
        if not callable(clock) or not callable(today):
            raise TypeError("clock and today must be callable")
        self._registry = registry
        self._clock = clock
        self._today = today

    async def test(self, market: Market, symbol: str) -> NetworkTestResult:
        config = self._registry.market_settings(market)
        provider = self._registry.get_ohlcv(market, config.provider)
        instrument, adjustment = _instrument_for(market, config.provider, symbol)
        end = self._today()
        start = end - timedelta(days=NETWORK_TEST_LOOKBACK_DAYS)
        started = self._clock()
        if provider_busy(config.provider):
            error = ProviderBusy()
            return _failure(
                market,
                config.provider,
                instrument.symbol,
                self._elapsed(started),
                type(error).__name__,
                error.public_detail,
            )
        try:
            rows = await call_provider_sync(
                _fetch_with_runtime,
                config.provider,
                config.proxy_url,
                provider,
                instrument,
                start,
                end,
                adjustment,
                timeout=config.request_timeout_seconds,
            )
        except ProviderError as error:
            return _failure(
                market,
                config.provider,
                instrument.symbol,
                self._elapsed(started),
                type(error).__name__,
                error.public_detail,
            )
        except Exception as error:
            logger.error(
                "Unexpected network test failure for %s/%s (%s)",
                market,
                config.provider,
                type(error).__name__,
            )
            return _failure(
                market,
                config.provider,
                instrument.symbol,
                self._elapsed(started),
                type(error).__name__,
                UNEXPECTED_TEST_ERROR,
            )
        if not rows:
            return _failure(
                market,
                config.provider,
                instrument.symbol,
                self._elapsed(started),
                "NoDataAvailable",
                EMPTY_PRICE_DETAIL,
            )
        latest = rows[-1]
        return NetworkTestResult(
            market=market,
            provider=config.provider,
            symbol=instrument.symbol,
            connected=True,
            latency_ms=self._elapsed(started),
            price=latest.close,
            price_date=latest.time,
            currency=instrument.currency,
        )

    def _elapsed(self, started: float) -> float:
        elapsed = (self._clock() - started) * 1_000
        if not math.isfinite(elapsed):
            raise ValueError("Network test clock returned an invalid duration")
        return round(max(0.0, elapsed), 1)


def _fetch_with_runtime(
    provider_name: str,
    proxy_url: str | None,
    provider: OhlcvProvider,
    instrument: InstrumentDTO,
    start: date,
    end: date,
    adjustment: Adjustment,
) -> object:
    with provider_runtime(provider_name, proxy_url, wait=False):
        return provider.fetch_daily(instrument, start, end, adjustment)


def _failure(
    market: Market,
    provider: str,
    symbol: str,
    latency_ms: float,
    error_type: str,
    detail: str,
) -> NetworkTestResult:
    return NetworkTestResult(
        market=market,
        provider=provider,
        symbol=symbol,
        connected=False,
        latency_ms=latency_ms,
        error_type=error_type,
        detail=detail,
    )


def _instrument_for(
    market: Market,
    provider_name: str,
    symbol: str,
) -> tuple[InstrumentDTO, Adjustment]:
    try:
        if market == "a_share":
            return _a_share_instrument(symbol), "qfq"
        if market == "hk_stock":
            return _hk_instrument(symbol), "qfq"
        if market == "us_stock":
            return _us_instrument(symbol), "qfq"
        entry = CryptoSymbol(exchange=provider_name, symbol=symbol.strip())  # type: ignore[arg-type]
        return crypto_instrument(entry), "none"
    except NetworkTestInputError:
        raise
    except (ProviderDataInvalid, ValueError):
        raise NetworkTestInputError() from None


def _a_share_instrument(symbol: str) -> InstrumentDTO:
    parsed = parse_a_share_symbol(symbol)
    prefix = parsed.prefix or _infer_a_prefix(parsed.code)
    if not parsed.code.startswith(_A_PREFIXES[prefix]):
        raise NetworkTestInputError()
    canonical = f"{parsed.code}.{prefix.upper()}"
    return InstrumentDTO(
        symbol=canonical,
        name=canonical,
        market="a_share",
        exchange=_A_EXCHANGES[prefix],
        currency="CNY",
        timezone="Asia/Shanghai",
        instrument_type="stock",
        provider_symbol=parsed.code,
    )


def _infer_a_prefix(code: str) -> str:
    for prefix, candidates in _A_PREFIXES.items():
        if code.startswith(candidates):
            return prefix
    raise NetworkTestInputError()


def _hk_instrument(symbol: str) -> InstrumentDTO:
    normalized = normalize_hk_stock_symbol(symbol)
    yahoo_code = normalized[1:] if len(normalized) == 5 and normalized.startswith("0") else normalized
    canonical = f"{yahoo_code}.HK"
    return InstrumentDTO(
        symbol=canonical,
        name=canonical,
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        instrument_type="stock",
        provider_symbol=canonical,
    )


def _us_instrument(symbol: str) -> InstrumentDTO:
    normalized = symbol.strip().upper()
    if len(normalized) > 32 or _US_SYMBOL_PATTERN.fullmatch(normalized) is None:
        raise NetworkTestInputError()
    return InstrumentDTO(
        symbol=normalized,
        name=normalized,
        market="us_stock",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        instrument_type="stock",
        provider_symbol=normalized,
    )
