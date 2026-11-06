"""Canonical, exchange-scoped instruments for configured crypto spot pairs."""

from types import MappingProxyType

from app.config.models import CryptoSymbol
from app.domain.dto import InstrumentDTO
from app.domain.spot_pairs import SPOT_PAIR_ERROR, parse_spot_pair as parse_domain_pair
from app.providers.errors import ProviderDataInvalid

EXCHANGE_NAMES = MappingProxyType({"binance": "Binance", "okx": "OKX"})


def parse_spot_pair(value: object) -> tuple[str, str]:
    """Translate domain validation into the provider error taxonomy."""
    try:
        return parse_domain_pair(value)
    except ValueError:
        raise ProviderDataInvalid(SPOT_PAIR_ERROR) from None


def crypto_instrument(entry: CryptoSymbol) -> InstrumentDTO:
    """Create a new immutable instrument without merging exchange identities."""
    if not isinstance(entry, CryptoSymbol):
        raise ProviderDataInvalid("Crypto catalog entry must be a CryptoSymbol")
    if not isinstance(entry.exchange, str) or entry.exchange not in EXCHANGE_NAMES:
        raise ProviderDataInvalid("Crypto catalog exchange is not supported")
    base, quote = parse_spot_pair(entry.symbol)
    exchange_name = EXCHANGE_NAMES[entry.exchange]
    return InstrumentDTO(
        symbol=f"{entry.exchange.upper()}:{entry.symbol}",
        name=f"{base}/{quote} {exchange_name} Spot",
        market="crypto",
        exchange=entry.exchange,
        currency=quote,
        timezone="UTC",
        instrument_type="crypto_spot",
        provider_symbol=entry.symbol,
    )
