"""Per-market immutable timeout snapshots in the production provider factory."""

from app.config.defaults import default_settings
from app.config.models import Settings
from app.providers.a_share_universes import AkshareUniverseProvider
from app.providers.akshare_ohlcv import AkshareOhlcvProvider
from app.providers.baostock_ohlcv import BaoStockOhlcvProvider
from app.providers.ccxt_ohlcv import CcxtOhlcvProvider
from app.providers.factory import build_provider_registry
from app.providers.hstech_universe import HstechUniverseProvider
from app.providers.invesco_universe import InvescoUniverseProvider
from app.providers.ishares_soxx import IsharesSoxxUniverseProvider
from app.providers.yahoo_ohlcv import YahooOhlcvProvider


def settings_with_timeouts() -> Settings:
    settings = default_settings()
    values = {"a_share": 11.0, "hk_stock": 22.0, "us_stock": 33.0, "crypto": 44.0}
    markets = {
        name: market.model_copy(
            update={
                "request_timeout_seconds": values[name],
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
    assert isinstance(binance, CcxtOhlcvProvider)
    assert isinstance(okx, CcxtOhlcvProvider)
    assert binance.request_timeout_seconds == okx.request_timeout_seconds == 44.0


def test_universe_adapters_receive_their_owning_market_timeout() -> None:
    registry = build_provider_registry(settings_with_timeouts())

    a_universe = registry.get_universe("csi300")
    hstech = registry.get_universe("hstech")
    invesco = registry.get_universe("nasdaq100")
    ishares = registry.get_universe("soxx")

    assert isinstance(a_universe, AkshareUniverseProvider)
    assert a_universe.request_timeout_seconds == 11.0
    assert isinstance(hstech, HstechUniverseProvider)
    assert hstech.request_timeout_seconds == 22.0
    assert isinstance(invesco, InvescoUniverseProvider)
    assert invesco.request_timeout_seconds == 33.0
    assert isinstance(ishares, IsharesSoxxUniverseProvider)
    assert ishares.request_timeout_seconds == 33.0
