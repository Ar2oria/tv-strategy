"""Latest-price network probes with isolated providers and no persistence."""

import asyncio
import logging
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Literal
from unittest.mock import Mock

import pytest

from app.config.defaults import default_settings
from app.config.models import Settings
from app.domain.dto import Adjustment, BarDTO, InstrumentDTO, Market
from app.providers.errors import ProviderUnavailable
from app.providers.registry import ProviderRegistry
from app.providers.sdk_runtime import provider_runtime
from app.services.market_network_test import (
    MarketNetworkTestService,
    NetworkTestInputError,
)

TODAY = date(2026, 11, 12)
LOOKBACK_START = TODAY - timedelta(days=31)


class RecordingProvider:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[InstrumentDTO, date | None, date, Adjustment]] = []

    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        self.calls.append((instrument, start, end, adjustment))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response  # type: ignore[return-value]


def bars(source: str, adjustment: Adjustment) -> list[BarDTO]:
    return [
        BarDTO(
            time=date(2026, 11, 10),
            open=90,
            high=95,
            low=85,
            close=91,
            volume=100,
            source=source,
            adjustment=adjustment,
        ),
        BarDTO(
            time=date(2026, 11, 11),
            open=98,
            high=105,
            low=96,
            close=101.5,
            volume=200,
            source=source,
            adjustment=adjustment,
        ),
    ]


def settings_for(market: Market, provider: str, proxy_url: str | None) -> Settings:
    settings = default_settings()
    updated = settings.markets[market].model_copy(
        update={"provider": provider, "proxy_url": proxy_url}
    )
    candidate = settings.model_copy(
        update={"markets": {**settings.markets, market: updated}}
    )
    return Settings.model_validate(candidate.model_dump(mode="python"))


def registry_for(
    market: Market,
    provider_name: str,
    proxy_url: str | None,
    provider: RecordingProvider,
) -> ProviderRegistry:
    return ProviderRegistry(
        settings=settings_for(market, provider_name, proxy_url),
        ohlcv_providers={provider_name: provider},  # type: ignore[dict-item]
    )


def install_runtime_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str | None, bool]]:
    calls: list[tuple[str, str | None, bool]] = []

    @contextmanager
    def fake_runtime(provider_name: str, proxy_url: str | None, *, wait: bool):
        calls.append((provider_name, proxy_url, wait))
        yield

    monkeypatch.setattr(
        "app.services.market_network_test.provider_runtime", fake_runtime
    )
    return calls


def service_for(
    registry: ProviderRegistry,
) -> MarketNetworkTestService:
    moments = iter((100.0, 100.123))
    return MarketNetworkTestService(
        registry,
        clock=lambda: next(moments),
        today=lambda: TODAY,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "market",
        "provider_name",
        "proxy_url",
        "input_symbol",
        "canonical_symbol",
        "exchange",
        "currency",
        "provider_symbol",
        "adjustment",
    ),
    [
        (
            "a_share",
            "akshare",
            "socks5://127.0.0.1:1080",
            "600519.SH",
            "600519.SH",
            "SSE",
            "CNY",
            "600519",
            "qfq",
        ),
        (
            "hk_stock",
            "yfinance",
            "http://127.0.0.1:8080",
            "0700.HK",
            "0700.HK",
            "HKEX",
            "HKD",
            "0700.HK",
            "qfq",
        ),
        (
            "us_stock",
            "yfinance",
            None,
            "AAPL",
            "AAPL",
            "NASDAQ",
            "USD",
            "AAPL",
            "qfq",
        ),
        (
            "crypto",
            "binance",
            "socks5h://127.0.0.1:1080",
            "BTC/USDT",
            "BINANCE:BTC/USDT",
            "binance",
            "USDT",
            "BTC/USDT",
            "none",
        ),
    ],
)
async def test_probe_returns_latest_daily_close_and_bounded_request(
    monkeypatch: pytest.MonkeyPatch,
    market: Market,
    provider_name: str,
    proxy_url: str | None,
    input_symbol: str,
    canonical_symbol: str,
    exchange: str,
    currency: str,
    provider_symbol: str,
    adjustment: Adjustment,
) -> None:
    provider = RecordingProvider(bars(provider_name, adjustment))
    registry = registry_for(market, provider_name, proxy_url, provider)
    runtime_calls = install_runtime_recorder(monkeypatch)
    before = registry.market_settings(market)

    result = await service_for(registry).test(market, input_symbol)

    assert result.connected is True
    assert result.market == market
    assert result.provider == provider_name
    assert result.symbol == canonical_symbol
    assert result.latency_ms == 123.0
    assert result.price == 101.5
    assert result.price_date == date(2026, 11, 11)
    assert result.currency == currency
    assert result.error_type is None
    assert result.detail is None
    assert runtime_calls == [(provider_name, proxy_url, False)]
    assert len(provider.calls) == 1
    instrument, start, end, requested_adjustment = provider.calls[0]
    assert (start, end, requested_adjustment) == (
        LOOKBACK_START,
        TODAY,
        adjustment,
    )
    assert instrument.symbol == canonical_symbol
    assert instrument.market == market
    assert instrument.exchange == exchange
    assert instrument.currency == currency
    assert instrument.provider_symbol == provider_symbol
    assert registry.market_settings(market) == before


@pytest.mark.anyio
async def test_empty_history_is_a_failed_price_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordingProvider([])
    registry = registry_for("us_stock", "yfinance", None, provider)
    install_runtime_recorder(monkeypatch)

    result = await service_for(registry).test("us_stock", "AAPL")

    assert result.connected is False
    assert result.error_type == "NoDataAvailable"
    assert result.detail == "No market data is available for the requested symbol"
    assert result.price is None
    assert result.price_date is None


@pytest.mark.anyio
async def test_provider_and_unexpected_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="app.services.market_network_test")
    provider = RecordingProvider(
        ProviderUnavailable(detail="CCXT binance OHLCV request failed (NetworkError)")
    )
    registry = registry_for("crypto", "binance", None, provider)
    install_runtime_recorder(monkeypatch)

    result = await service_for(registry).test("crypto", "BTC/USDT")

    assert result.connected is False
    assert result.error_type == "ProviderUnavailable"
    assert result.detail == "CCXT binance OHLCV request failed (NetworkError)"

    unexpected = RecordingProvider(RuntimeError("private proxy credential"))
    unexpected_registry = registry_for("us_stock", "yfinance", None, unexpected)
    failure = await service_for(unexpected_registry).test("us_stock", "AAPL")

    assert failure.connected is False
    assert failure.error_type == "RuntimeError"
    assert failure.detail == "Network test failed"
    assert "private proxy credential" not in str(failure)
    assert "private proxy credential" not in caplog.text
    assert "Traceback" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("market", "provider_name", "symbol"),
    [
        ("a_share", "akshare", "600519.SH"),
        ("us_stock", "yfinance", "AAPL"),
        ("a_share", "baostock", "600519.SH"),
    ],
)
async def test_busy_sdk_returns_immediately_without_calling_the_provider(
    monkeypatch: pytest.MonkeyPatch,
    market: Market,
    provider_name: Literal["akshare", "yfinance", "baostock"],
    symbol: str,
) -> None:
    provider = RecordingProvider([])
    registry = registry_for(market, provider_name, None, provider)
    moments = iter((10.0, 10.005))
    service = MarketNetworkTestService(
        registry,
        clock=lambda: next(moments),
        today=lambda: TODAY,
    )
    started = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with provider_runtime(provider_name, None, wait=True):
            started.set()
            release.wait(timeout=2)

    worker = threading.Thread(target=hold_lock)
    worker.start()
    assert started.wait(timeout=1)
    provider_sync = Mock(side_effect=AssertionError("executor was scheduled"))
    monkeypatch.setattr(
        "app.services.market_network_test.call_provider_sync", provider_sync
    )
    try:
        result = await asyncio.wait_for(service.test(market, symbol), timeout=0.2)
    finally:
        release.set()
        worker.join(timeout=1)

    assert result.connected is False
    assert result.error_type == "ProviderBusy"
    assert result.detail == "Data source is currently in use, retry later"
    assert result.latency_ms == 5.0
    assert provider.calls == []
    provider_sync.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("market", "symbol"),
    [
        ("a_share", "bad symbol"),
        ("hk_stock", "HK700"),
        ("us_stock", "bad symbol"),
        ("crypto", "btc/USDT"),
        ("crypto", "BTC-PERP"),
    ],
)
async def test_invalid_symbols_fail_before_provider_access(
    market: Market,
    symbol: str,
) -> None:
    provider_name = "binance" if market == "crypto" else "akshare" if market != "us_stock" else "yfinance"
    provider = RecordingProvider([])
    registry = registry_for(market, provider_name, None, provider)
    service = service_for(registry)

    with pytest.raises(NetworkTestInputError):
        await service.test(market, symbol)

    assert provider.calls == []
