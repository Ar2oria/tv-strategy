"""Per-market immutable timeout snapshots in the production provider factory."""

from pathlib import Path

import pytest

from app.config.defaults import default_settings
from app.config.models import Settings
from app.providers.a_share_universes import AkshareUniverseProvider
from app.providers.akshare_ohlcv import AkshareOhlcvProvider
from app.providers.baostock_ohlcv import BaoStockOhlcvProvider
from app.providers.ccxt_ohlcv import CcxtOhlcvProvider
from app.providers.factory import build_provider_registry
from app.providers.hstech_api import ItigerUniverseProvider
from app.providers.invesco_universe import InvescoUniverseProvider
from app.providers.ishares_soxx import IsharesSoxxUniverseProvider
from app.providers.yahoo_ohlcv import YahooOhlcvProvider


def settings_with_timeouts() -> Settings:
    settings = default_settings()
    values = {"a_share": 11.0, "hk_stock": 22.0, "us_stock": 33.0, "crypto": 44.0}
    proxies = {
        "a_share": "socks5://127.0.0.1:1080",
        "hk_stock": "socks5h://127.0.0.1:1081",
        "us_stock": "http://127.0.0.1:8080",
        "crypto": "socks5h://127.0.0.1:1082",
    }
    markets = {
        name: market.model_copy(
            update={
                "request_timeout_seconds": values[name],
                "proxy_url": proxies[name],
                **({"provider": "yfinance"} if name == "hk_stock" else {}),
            }
        )
        for name, market in settings.markets.items()
    }
    return Settings.model_validate(
        settings.model_copy(update={"markets": markets}).model_dump(mode="python")
    )


def test_ohlcv_adapters_receive_their_own_market_timeout() -> None:
    registry = build_provider_registry(settings_with_timeouts())

    a_akshare = registry.get_ohlcv("a_share", "akshare")
    hk_akshare = registry.get_ohlcv("hk_stock", "akshare")
    hk_yahoo = registry.get_ohlcv("hk_stock", "yfinance")
    us_yahoo = registry.get_ohlcv("us_stock")
    baostock = registry.get_ohlcv("a_share", "baostock")
    binance = registry.get_ohlcv("crypto", "binance")
    okx = registry.get_ohlcv("crypto", "okx")

    assert isinstance(a_akshare, AkshareOhlcvProvider)
    assert isinstance(hk_akshare, AkshareOhlcvProvider)
    assert a_akshare is not hk_akshare
    assert a_akshare.request_timeout_seconds == 11.0
    assert hk_akshare.request_timeout_seconds == 22.0
    assert isinstance(baostock, BaoStockOhlcvProvider)
    assert baostock.request_timeout_seconds == 11.0
    assert isinstance(hk_yahoo, YahooOhlcvProvider)
    assert isinstance(us_yahoo, YahooOhlcvProvider)
    assert hk_yahoo is not us_yahoo
    assert hk_yahoo.request_timeout_seconds == 22.0
    assert us_yahoo.request_timeout_seconds == 33.0
    assert a_akshare.proxy_url == "socks5://127.0.0.1:1080"
    assert hk_akshare.proxy_url == "socks5h://127.0.0.1:1081"
    assert hk_yahoo.proxy_url == "socks5h://127.0.0.1:1081"
    assert us_yahoo.proxy_url == "http://127.0.0.1:8080"
    assert isinstance(binance, CcxtOhlcvProvider)
    assert isinstance(okx, CcxtOhlcvProvider)
    assert binance.request_timeout_seconds == okx.request_timeout_seconds == 44.0


def test_ccxt_adapters_receive_the_crypto_proxy_without_sharing_state() -> None:
    registry = build_provider_registry(settings_with_timeouts())

    binance = registry.get_ohlcv("crypto", "binance")
    okx = registry.get_ohlcv("crypto", "okx")

    assert isinstance(binance, CcxtOhlcvProvider)
    assert isinstance(okx, CcxtOhlcvProvider)
    assert binance is not okx
    assert binance.proxy_url == "socks5h://127.0.0.1:1082"
    assert okx.proxy_url == "socks5h://127.0.0.1:1082"


def test_universe_adapters_receive_their_owning_market_timeout() -> None:
    registry = build_provider_registry(settings_with_timeouts())

    a_universe = registry.get_universe("csi300")
    hstech = registry.get_universe("hstech")
    invesco = registry.get_universe("nasdaq100")
    ishares = registry.get_universe("soxx")

    assert isinstance(a_universe, AkshareUniverseProvider)
    assert a_universe.request_timeout_seconds == 11.0
    assert a_universe.proxy_url == "socks5://127.0.0.1:1080"
    assert isinstance(hstech, ItigerUniverseProvider)
    assert hstech.request_timeout_seconds == 22.0
    assert isinstance(invesco, InvescoUniverseProvider)
    assert invesco.request_timeout_seconds == 33.0
    assert isinstance(ishares, IsharesSoxxUniverseProvider)
    assert ishares.request_timeout_seconds == 33.0
    assert hstech.proxy_url == "socks5h://127.0.0.1:1081"
    assert invesco.proxy_url == "http://127.0.0.1:8080"
    assert ishares.proxy_url == "http://127.0.0.1:8080"


def test_itiger_token_prefers_the_persisted_task_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ITIGER_BEARER_TOKEN", "env-token")
    settings = settings_with_timeouts()
    task = settings.tasks["market.sync_universes"].model_copy(
        update={"params": {"itiger_token": "configured-token"}}
    )
    settings = Settings.model_validate(
        settings.model_copy(
            update={"tasks": {**settings.tasks, "market.sync_universes": task}}
        ).model_dump(mode="python")
    )

    provider = build_provider_registry(settings).get_universe("hstech")

    assert isinstance(provider, ItigerUniverseProvider)
    assert provider.bearer_token == "configured-token"


def test_itiger_token_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ITIGER_BEARER_TOKEN", "dummy-test-token")

    provider = build_provider_registry(settings_with_timeouts()).get_universe("hstech")

    assert isinstance(provider, ItigerUniverseProvider)
    assert provider.bearer_token == "dummy-test-token"


def test_itiger_token_falls_back_to_the_original_local_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("ITIGER_BEARER_TOKEN", raising=False)
    token_file = tmp_path / "itiger_token.txt"
    token_file.write_text("original-default-token\n", encoding="utf-8")
    monkeypatch.setattr("app.config.itiger_token.ITIGER_TOKEN_FILE", token_file)

    provider = build_provider_registry(settings_with_timeouts()).get_universe("hstech")

    assert isinstance(provider, ItigerUniverseProvider)
    assert provider.bearer_token == "original-default-token"
