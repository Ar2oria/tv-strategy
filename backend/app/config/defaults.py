"""Factory for the initial backend configuration."""

from app.config.models import (
    DEFAULT_TIMEZONE,
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


def default_settings() -> Settings:
    """Create fresh defaults so callers never share nested mutable values."""
    return Settings(
        schema_version=1,
        revision=0,
        markets={
            "a_share": MarketSettings(
                provider="akshare",
            ),
            "hk_stock": MarketSettings(
                provider="akshare",
            ),
            "us_stock": MarketSettings(
                provider="yfinance",
            ),
            "crypto": MarketSettings(provider="binance"),
        },
        timezone=DEFAULT_TIMEZONE,
        indicators=IndicatorSettings(),
        tasks={
            **{
                name: TaskSettings(enabled=False)
                for name in (PURGE_TASK_HISTORY, *BUILTIN_MARKET_TASKS)
                if name != "market.sync_crypto_daily"
            },
            "market.sync_crypto_daily": TaskSettings(
                enabled=False,
                params={
                    "spot_pairs": [
                        {"exchange": "binance", "symbol": "BTC/USDT"},
                        {"exchange": "binance", "symbol": "ETH/USDT"},
                    ]
                },
            ),
        },
    )
