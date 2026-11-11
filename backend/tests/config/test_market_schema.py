"""Contract tests for per-market, scheduler, task, and indicator settings."""

import pytest
from pydantic import ValidationError

from app.config.defaults import default_settings
from app.config.models import (
    IndicatorSettings,
    MarketSettings,
    Settings,
    TaskSettings,
)

CLEANUP_TASK = "system.purge_task_history"
STOCK_MARKETS = ("a_share", "hk_stock", "us_stock")
EXPECTED_PROVIDERS = {
    "a_share": "akshare",
    "hk_stock": "akshare",
    "us_stock": "yfinance",
    "crypto": "binance",
}


def revalidate(settings: Settings) -> Settings:
    """Round-trip through validation after deliberately unvalidated copies."""
    return Settings.model_validate(settings.model_dump(mode="python"))


def replace_market(
    settings: Settings,
    market_name: str,
    **changes: object,
) -> Settings:
    market = settings.markets[market_name].model_copy(update=changes)
    candidate = settings.model_copy(
        update={"markets": {**settings.markets, market_name: market}}
    )
    return revalidate(candidate)


def test_default_markets_and_request_strategies_match_contract() -> None:
    settings = default_settings()

    assert set(settings.markets) == set(EXPECTED_PROVIDERS)
    assert {
        name: market.provider for name, market in settings.markets.items()
    } == EXPECTED_PROVIDERS
    for market in settings.markets.values():
        assert "symbols" not in market.model_fields_set
        assert market.request_timeout_seconds == 20
    assert settings.tasks["market.sync_crypto_daily"].params["spot_pairs"] == [
        {"exchange": "binance", "symbol": "BTC/USDT"},
        {"exchange": "binance", "symbol": "ETH/USDT"},
    ]


def test_global_scheduler_and_indicator_defaults_match_contract() -> None:
    settings = default_settings()

    assert settings.schema_version == 1
    assert settings.revision == 0
    assert settings.timezone == "UTC"
    assert settings.indicators == IndicatorSettings()
    assert settings.indicators.max_active_indicators == 20
    assert settings.tasks[CLEANUP_TASK].enabled is False
    assert settings.tasks[CLEANUP_TASK].params == {}
    assert "timezone" not in TaskSettings.model_fields
    assert "stock" not in Settings.model_fields
    assert "crypto" not in Settings.model_fields


def test_market_strategy_defaults_and_valid_upper_bounds() -> None:
    defaults = MarketSettings(provider="akshare")
    bounded = MarketSettings(
        provider="akshare",
        request_timeout_seconds=300,
    )

    assert "symbols" not in MarketSettings.model_fields
    assert defaults.request_timeout_seconds == 20
    assert bounded.request_timeout_seconds == 300


@pytest.mark.parametrize("provider", ["", "   "])
def test_market_provider_must_be_nonempty(provider: str) -> None:
    with pytest.raises(ValidationError):
        MarketSettings(provider=provider)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("request_timeout_seconds", 0),
        ("request_timeout_seconds", 300.01),
    ],
)
def test_market_strategy_rejects_out_of_range_values(
    field: str,
    invalid_value: float,
) -> None:
    with pytest.raises(ValidationError):
        MarketSettings(
            provider="akshare",
            **{field: invalid_value},
        )


@pytest.mark.parametrize(
    "field",
    ["history_years", "overlap_days", "concurrency", "max_retries", "symbols"],
)
def test_market_strategy_rejects_retired_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        MarketSettings(provider="akshare", **{field: 1})


@pytest.mark.parametrize(
    ("market_name", "provider"),
    [
        ("a_share", "baostock"),
        ("hk_stock", "yfinance"),
        ("crypto", "okx"),
    ],
)
def test_allowed_provider_alternatives_validate(
    market_name: str,
    provider: str,
) -> None:
    settings = replace_market(
        default_settings(), market_name, provider=provider
    )

    assert settings.markets[market_name].provider == provider


@pytest.mark.parametrize(
    ("market_name", "provider"),
    [
        ("a_share", "yfinance"),
        ("hk_stock", "baostock"),
        ("hk_stock", "yahoo"),
        ("us_stock", "akshare"),
        ("crypto", "akshare"),
    ],
)
def test_disallowed_market_provider_is_rejected(
    market_name: str,
    provider: str,
) -> None:
    with pytest.raises(ValidationError, match="provider"):
        replace_market(default_settings(), market_name, provider=provider)


def test_exact_market_key_set_is_enforced() -> None:
    settings = default_settings()
    without_crypto = {
        name: market
        for name, market in settings.markets.items()
        if name != "crypto"
    }
    with_extra = {
        **settings.markets,
        "forex": MarketSettings(provider="binance"),
    }

    with pytest.raises(ValidationError, match="market"):
        revalidate(settings.model_copy(update={"markets": without_crypto}))
    with pytest.raises(ValidationError, match="market"):
        revalidate(settings.model_copy(update={"markets": with_extra}))


def test_global_timezone_is_validated() -> None:
    valid = default_settings().model_copy(update={"timezone": "Asia/Shanghai"})
    invalid = default_settings().model_copy(
        update={"timezone": "Mars/Olympus_Mons"}
    )

    assert revalidate(valid).timezone == "Asia/Shanghai"
    with pytest.raises(ValidationError, match="timezone"):
        revalidate(invalid)


@pytest.mark.parametrize(
    "cron",
    [
        "0 0 * * * *",
        "0 0 * *",
        "not a cron expression",
    ],
)
def test_task_cron_must_be_valid_with_exactly_five_fields(cron: str) -> None:
    with pytest.raises(ValidationError):
        TaskSettings(cron=cron)


def test_task_params_are_json_and_task_timezone_is_forbidden() -> None:
    params = {
        "lookback": 30,
        "threshold": 1.25,
        "enabled": True,
        "filters": ["liquid", None],
        "nested": {"name": "daily"},
    }

    task = TaskSettings(cron="*/5 * * * *", params=params)

    assert task.params == params
    with pytest.raises(ValidationError):
        TaskSettings.model_validate({"timezone": "UTC"})
    with pytest.raises(ValidationError):
        TaskSettings.model_validate({"params": {"invalid": object()}})


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("max_active_indicators", 0),
        ("max_active_indicators", 101),
    ],
)
def test_indicator_limits_are_bounded(
    field: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValidationError):
        IndicatorSettings(**{field: invalid_value})


def test_removed_point_limit_field_is_rejected() -> None:
    """The old max_points_per_indicator key must fail fast, not load silently."""
    with pytest.raises(ValidationError):
        IndicatorSettings(max_points_per_indicator=50000)
