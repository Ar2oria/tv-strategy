"""Construct provider registries with immutable per-market settings snapshots."""

from app.config.defaults import default_settings
from app.config.itiger_token import default_itiger_token
from app.config.models import Settings
from app.providers.a_share_universes import AkshareUniverseProvider
from app.providers.akshare_ohlcv import AkshareOhlcvProvider
from app.providers.baostock_ohlcv import BaoStockOhlcvProvider
from app.providers.base import OhlcvProvider, UniverseProvider
from app.providers.ccxt_ohlcv import CcxtOhlcvProvider
from app.providers.hstech_api import ItigerUniverseProvider
from app.providers.invesco_universe import InvescoUniverseProvider
from app.providers.ishares_soxx import IsharesSoxxUniverseProvider
from app.providers.registry import ProviderRegistry
from app.providers.yahoo_ohlcv import YahooOhlcvProvider


def default_ohlcv_providers() -> dict[str, OhlcvProvider]:
    """Retain the flat default mapping for backward-compatible injection."""
    return {
        "akshare": AkshareOhlcvProvider(),
        "baostock": BaoStockOhlcvProvider(),
        "yfinance": YahooOhlcvProvider(),
        "binance": CcxtOhlcvProvider("binance"),
        "okx": CcxtOhlcvProvider("okx"),
    }


def market_ohlcv_providers(
    settings: Settings,
) -> dict[str, dict[str, OhlcvProvider]]:
    """Build distinct adapters so one market's timeout cannot leak to another."""
    markets = settings.markets
    a_timeout = markets["a_share"].request_timeout_seconds
    hk_timeout = markets["hk_stock"].request_timeout_seconds
    us_timeout = markets["us_stock"].request_timeout_seconds
    a_proxy = markets["a_share"].proxy_url
    hk_proxy = markets["hk_stock"].proxy_url
    us_proxy = markets["us_stock"].proxy_url
    crypto_timeout = markets["crypto"].request_timeout_seconds
    crypto_proxy = markets["crypto"].proxy_url
    return {
        "a_share": {
            "akshare": AkshareOhlcvProvider(
                request_timeout_seconds=a_timeout, proxy_url=a_proxy
            ),
            "baostock": BaoStockOhlcvProvider(request_timeout_seconds=a_timeout),
        },
        "hk_stock": {
            "akshare": AkshareOhlcvProvider(
                request_timeout_seconds=hk_timeout, proxy_url=hk_proxy
            ),
            "yfinance": YahooOhlcvProvider(
                request_timeout_seconds=hk_timeout, proxy_url=hk_proxy
            ),
        },
        "us_stock": {
            "yfinance": YahooOhlcvProvider(
                request_timeout_seconds=us_timeout, proxy_url=us_proxy
            ),
        },
        "crypto": {
            "binance": CcxtOhlcvProvider(
                "binance",
                request_timeout_seconds=crypto_timeout,
                proxy_url=crypto_proxy,
            ),
            "okx": CcxtOhlcvProvider(
                "okx",
                request_timeout_seconds=crypto_timeout,
                proxy_url=crypto_proxy,
            ),
        },
    }


def default_universe_providers(
    settings: Settings | None = None,
) -> dict[str, UniverseProvider]:
    """Register every supported universe with its owning market's timeout."""
    snapshot = default_settings() if settings is None else settings
    markets = snapshot.markets
    akshare = AkshareUniverseProvider(
        request_timeout_seconds=markets["a_share"].request_timeout_seconds,
        proxy_url=markets["a_share"].proxy_url,
    )
    return {
        "csi300": akshare,
        "star_market": akshare,
        "chinext": akshare,
        "hstech": ItigerUniverseProvider(
            request_timeout_seconds=markets["hk_stock"].request_timeout_seconds,
            proxy_url=markets["hk_stock"].proxy_url,
            bearer_token=default_itiger_token(snapshot),
        ),
        "nasdaq100": InvescoUniverseProvider(
            request_timeout_seconds=markets["us_stock"].request_timeout_seconds,
            proxy_url=markets["us_stock"].proxy_url,
        ),
        "soxx": IsharesSoxxUniverseProvider(
            request_timeout_seconds=markets["us_stock"].request_timeout_seconds,
            proxy_url=markets["us_stock"].proxy_url,
        ),
    }


def build_provider_registry(settings: Settings) -> ProviderRegistry:
    """Build a fresh immutable snapshot for initial startup or hot apply."""
    snapshot = settings.model_copy(deep=True)
    return ProviderRegistry(
        settings=snapshot,
        market_ohlcv_providers=market_ohlcv_providers(snapshot),
        universe_providers=default_universe_providers(snapshot),
    )
