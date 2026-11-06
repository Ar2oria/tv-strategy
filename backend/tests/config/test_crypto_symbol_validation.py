"""Strict spot-pair validation at the persisted-settings boundary."""

import pytest
from pydantic import ValidationError

from app.config.models import CryptoSymbol, MarketSettings
from app.providers.crypto_catalog import crypto_instrument


@pytest.mark.parametrize(
    "pair",
    [
        "btc/USDT",
        "BTC/usdt",
        " BTC/USDT",
        "BTC/USDT ",
        "BTC/USDT:USDT",
        "BTC-PERP",
        "BTC/USDT/USD",
        "BTC-USDT",
        "BTC//USDT",
        "",
        " ",
    ],
)
def test_settings_reject_lowercase_derivative_and_malformed_pairs(pair: str) -> None:
    with pytest.raises(ValidationError, match="uppercase BASE/QUOTE spot pair"):
        CryptoSymbol(exchange="binance", symbol=pair)

    with pytest.raises(ValidationError, match="uppercase BASE/QUOTE spot pair"):
        MarketSettings(
            provider="binance",
            history_years=None,
            symbols=[{"exchange": "binance", "symbol": pair}],
        )


def test_valid_pair_retains_exact_exchange_qualified_identity() -> None:
    entry = CryptoSymbol(exchange="okx", symbol="1000SHIB/USDT")

    instrument = crypto_instrument(entry)

    assert entry.symbol == "1000SHIB/USDT"
    assert instrument.symbol == "OKX:1000SHIB/USDT"
    assert instrument.provider_symbol == "1000SHIB/USDT"
    assert instrument.currency == "USDT"
