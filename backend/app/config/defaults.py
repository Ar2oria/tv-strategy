"""Factory for the initial backend configuration."""

from app.config.models import (
    DEFAULT_TIMEZONE,
    CryptoSymbol,
    IndicatorSettings,
    MarketSettings,
    Settings,
    TaskSettings,
)

PURGE_TASK_HISTORY = "system.purge_task_history"
BUILTIN_MARKET_TASKS = (
    "market.sync_universes",
    "market.sync_a_daily",
    "market.sync_hk_daily",
    "market.sync_us_daily",
    "market.sync_crypto_daily",
)
STOCK_HISTORY_YEARS = 10


def default_settings() -> Settings:
    """Create fresh defaults so callers never share nested mutable values."""
    return Settings(
        schema_version=1,
        revision=0,
        markets={
            "a_share": MarketSettings(
                provider="akshare",
                history_years=STOCK_HISTORY_YEARS,
            ),
            "hk_stock": MarketSettings(
                provider="akshare",
                history_years=STOCK_HISTORY_YEARS,
            ),
            "us_stock": MarketSettings(
                provider="yfinance",
                history_years=STOCK_HISTORY_YEARS,
            ),
            "crypto": MarketSettings(
                provider="binance",
                symbols=[
                    CryptoSymbol(exchange="binance", symbol="BTC/USDT"),
                    CryptoSymbol(exchange="binance", symbol="ETH/USDT"),
                ],
                history_years=None,
            ),
        },
        timezone=DEFAULT_TIMEZONE,
        indicators=IndicatorSettings(),
        tasks={
            name: TaskSettings(enabled=False)
            for name in (PURGE_TASK_HISTORY, *BUILTIN_MARKET_TASKS)
        },
    )
