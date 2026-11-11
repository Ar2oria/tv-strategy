"""Frozen, strictly validated configuration models."""

from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from app.domain.spot_pairs import parse_spot_pair
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

DEFAULT_TASK_CRON = "0 0 * * *"
DEFAULT_TIMEZONE = "UTC"
ALLOWED_MARKET_PROVIDERS = {
    "a_share": frozenset({"akshare", "baostock"}),
    "hk_stock": frozenset({"akshare", "yfinance"}),
    "us_stock": frozenset({"yfinance"}),
    "crypto": frozenset({"binance", "okx"}),
}
CRON_FIELD_COUNT = 5


class FrozenSettingsModel(BaseModel):
    """Base model that rejects unknown fields and attribute mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CryptoSymbol(FrozenSettingsModel):
    """A crypto market symbol scoped to a supported exchange."""

    exchange: Literal["binance", "okx"]
    symbol: str

    @field_validator("symbol")
    @classmethod
    def symbol_must_be_canonical_spot_pair(cls, value: str) -> str:
        parse_spot_pair(value)
        return value


class MarketSettings(FrozenSettingsModel):
    """Provider and request timeout for one market."""

    provider: str = Field(min_length=1)
    request_timeout_seconds: float = Field(default=20, gt=0, le=300)

    @field_validator("provider")
    @classmethod
    def provider_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Market provider must not be blank")
        return value


class TaskSettings(FrozenSettingsModel):
    """Scheduling configuration and JSON parameters for a named task."""

    enabled: bool = False
    cron: str = DEFAULT_TASK_CRON
    params: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("cron")
    @classmethod
    def cron_must_be_valid_five_field_expression(cls, value: str) -> str:
        if len(value.split()) != CRON_FIELD_COUNT:
            raise ValueError(
                "Cron expression must contain exactly five "
                "whitespace-separated fields"
            )
        if not croniter.is_valid(value):
            raise ValueError(f"Invalid cron expression: {value!r}")
        return value


class IndicatorSettings(FrozenSettingsModel):
    """Global limits for configured indicators."""

    max_active_indicators: int = Field(default=20, ge=1, le=100)


class Settings(FrozenSettingsModel):
    """Complete versioned backend configuration document."""

    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    markets: dict[str, MarketSettings]
    timezone: str = DEFAULT_TIMEZONE
    indicators: IndicatorSettings = Field(default_factory=IndicatorSettings)
    tasks: dict[str, TaskSettings] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Invalid IANA timezone: {value!r}") from error
        return value

    @model_validator(mode="after")
    def markets_must_match_contract(self) -> Self:
        expected = frozenset(ALLOWED_MARKET_PROVIDERS)
        actual = frozenset(self.markets)
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            raise ValueError(
                "market key set must be exact; "
                f"missing={missing}, unexpected={unexpected}"
            )

        for name, allowed_providers in ALLOWED_MARKET_PROVIDERS.items():
            market = self.markets[name]
            if market.provider not in allowed_providers:
                raise ValueError(
                    f"provider {market.provider!r} is not allowed for "
                    f"market {name!r}; expected {sorted(allowed_providers)}"
                )
        return self
