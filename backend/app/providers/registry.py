"""Validated provider selection against the final application Settings."""

from collections.abc import Mapping
from types import MappingProxyType

from app.config.models import ALLOWED_MARKET_PROVIDERS, MarketSettings, Settings
from app.providers.base import OhlcvProvider, UniverseProvider
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderUnavailable,
    UnknownMarketError,
    UnknownProviderError,
)

KNOWN_OHLCV_PROVIDERS = frozenset().union(*ALLOWED_MARKET_PROVIDERS.values())


class ProviderRegistry:
    """Resolve immutable provider mappings without performing provider I/O."""

    def __init__(
        self,
        *,
        settings: Settings,
        ohlcv_providers: Mapping[str, OhlcvProvider] | None = None,
        market_ohlcv_providers: Mapping[
            str, Mapping[str, OhlcvProvider]
        ] | None = None,
        universe_providers: Mapping[str, UniverseProvider] | None = None,
    ) -> None:
        if not isinstance(settings, Settings):
            raise TypeError("settings must be the final Settings model")
        self._settings = Settings.model_validate(
            settings.model_dump(mode="python")
        )
        ohlcv_snapshot = dict(ohlcv_providers or {})
        unknown_names = frozenset(ohlcv_snapshot) - KNOWN_OHLCV_PROVIDERS
        if unknown_names:
            raise UnknownProviderError()
        self._ohlcv_providers = MappingProxyType(ohlcv_snapshot)
        market_snapshot = dict(market_ohlcv_providers or {})
        unknown_markets = frozenset(market_snapshot) - frozenset(
            ALLOWED_MARKET_PROVIDERS
        )
        if unknown_markets:
            raise UnknownMarketError()
        for providers in market_snapshot.values():
            if frozenset(providers) - KNOWN_OHLCV_PROVIDERS:
                raise UnknownProviderError()
        self._market_ohlcv_providers = MappingProxyType(
            {
                market: MappingProxyType(dict(providers))
                for market, providers in market_snapshot.items()
            }
        )
        self._universe_providers = MappingProxyType(
            dict(universe_providers or {})
        )

    def market_settings(self, market: str) -> MarketSettings:
        """Return one market's immutable configuration from this registry snapshot."""
        if market not in ALLOWED_MARKET_PROVIDERS:
            raise UnknownMarketError()
        return self._settings.markets[market].model_copy(deep=True)

    def get_ohlcv(
        self,
        market: str,
        provider_name: str | None = None,
    ) -> OhlcvProvider:
        """Select an explicitly compatible provider or the configured default."""
        if market not in ALLOWED_MARKET_PROVIDERS:
            raise UnknownMarketError()
        selected_name = (
            self._settings.markets[market].provider
            if provider_name is None
            else provider_name
        )
        if selected_name not in KNOWN_OHLCV_PROVIDERS:
            raise UnknownProviderError()
        if selected_name not in ALLOWED_MARKET_PROVIDERS[market]:
            raise ProviderCompatibilityError()
        providers = self._market_ohlcv_providers.get(
            market,
            self._ohlcv_providers,
        )
        try:
            return providers[selected_name]
        except KeyError:
            raise ProviderUnavailable() from None

    def get_universe(self, universe_code: str) -> UniverseProvider:
        """Resolve the provider registered for one exact universe code."""
        try:
            return self._universe_providers[universe_code]
        except KeyError:
            raise UnknownProviderError("Unknown universe provider") from None
