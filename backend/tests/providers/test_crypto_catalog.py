"""Canonical crypto spot instrument mapping tests."""

from dataclasses import FrozenInstanceError

import pytest

from app.config.models import CryptoSymbol
from app.domain.dto import InstrumentDTO
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import ProviderDataInvalid


def test_binance_and_okx_pairs_are_distinct_canonical_instruments() -> None:
    binance = crypto_instrument(CryptoSymbol(exchange="binance", symbol="BTC/USDT"))
    okx = crypto_instrument(CryptoSymbol(exchange="okx", symbol="BTC/USDT"))

    assert binance.symbol == "BINANCE:BTC/USDT"
    assert okx.symbol == "OKX:BTC/USDT"
    assert binance.symbol != okx.symbol
    assert binance != okx
    assert binance.market == okx.market == "crypto"
    assert binance.exchange == "binance"
    assert okx.exchange == "okx"
    assert binance.provider_symbol == okx.provider_symbol == "BTC/USDT"
    assert binance.currency == okx.currency == "USDT"
    assert binance.timezone == okx.timezone == "UTC"
    assert binance.instrument_type == okx.instrument_type == "crypto_spot"
    assert "BTC/USDT" in binance.name
    assert "BTC/USDT" in okx.name


@pytest.mark.parametrize(
    ("exchange", "pair", "canonical", "quote"),
    [
        ("binance", "ETH/BTC", "BINANCE:ETH/BTC", "BTC"),
        ("okx", "SOL/USDC", "OKX:SOL/USDC", "USDC"),
        ("binance", "1INCH/EUR", "BINANCE:1INCH/EUR", "EUR"),
        ("okx", "1000SHIB/USDT", "OKX:1000SHIB/USDT", "USDT"),
    ],
)
def test_quote_currency_and_provider_symbol_come_from_exact_spot_pair(
    exchange: str, pair: str, canonical: str, quote: str
) -> None:
    entry = CryptoSymbol(exchange=exchange, symbol=pair)  # type: ignore[arg-type]

    result = crypto_instrument(entry)

    assert result.symbol == canonical
    assert result.provider_symbol == pair
    assert result.currency == quote
    assert result.exchange == exchange


@pytest.mark.parametrize(
    "pair",
    [
        "BTC/USDT:USDT",
        "BTC/USD:BTC",
        "BTC-PERP",
        "BTC/USDT/USD",
        "BTC//USDT",
        "/USDT",
        "BTC/",
        "BTC-USDT",
        "BTC_USDT",
        "BTC USDT",
        "btc/USDT",
        "BTC/usdt",
        " BTC/USDT",
        "BTC/USDT ",
        "BTC /USDT",
        "BTC/ USDT",
        "BTC/USDT;DROP",
        "BTC/USDT\n",
        "BTC.USDT",
    ],
)
def test_derivative_malformed_and_noncanonical_pairs_are_rejected(pair: str) -> None:
    entry = CryptoSymbol.model_construct(exchange="binance", symbol=pair)

    with pytest.raises(ProviderDataInvalid, match="spot pair"):
        crypto_instrument(entry)


@pytest.mark.parametrize("pair", ["", " ", "BTC/USDT"])
def test_model_construct_cannot_bypass_catalog_boundaries(pair: str) -> None:
    entry = CryptoSymbol.model_construct(exchange="not-an-exchange", symbol=pair)

    with pytest.raises(ProviderDataInvalid):
        crypto_instrument(entry)


def test_blank_pair_is_rejected_even_if_model_validation_was_bypassed() -> None:
    entry = CryptoSymbol.model_construct(exchange="binance", symbol=" ")

    with pytest.raises(ProviderDataInvalid, match="spot pair"):
        crypto_instrument(entry)


def test_non_crypto_symbol_input_is_rejected() -> None:
    with pytest.raises(ProviderDataInvalid, match="CryptoSymbol"):
        crypto_instrument({"exchange": "binance", "symbol": "BTC/USDT"})  # type: ignore[arg-type]


def test_result_is_an_immutable_instrument_dto() -> None:
    result = crypto_instrument(CryptoSymbol(exchange="okx", symbol="ETH/USDT"))

    assert isinstance(result, InstrumentDTO)
    with pytest.raises(FrozenInstanceError):
        result.currency = "BTC"  # type: ignore[misc]
