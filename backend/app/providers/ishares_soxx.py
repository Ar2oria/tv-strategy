"""Bounded iShares SOXX CSV adapter for the current equity constituents."""

import csv
import re
from datetime import date, datetime
from io import StringIO

from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.providers.errors import ProviderCompatibilityError, ProviderDataInvalid
from app.providers.http import fetch_bytes
from app.providers.timeouts import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    validate_request_timeout,
)

SOXX_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239705/ishares-semiconductor-etf/"
    "latest-holdings.csv"
)
SOURCE = "ishares"
SOXX_MAX_BYTES = 8 * 1024 * 1024
SOXX_TIMEOUT_SECONDS = DEFAULT_REQUEST_TIMEOUT_SECONDS
_REQUIRED_HEADER = ("Ticker", "Name", "Sector", "Asset Class")
_TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*")
_MAX_TICKER_LENGTH = 32
_MAX_NAME_LENGTH = 256
_MAX_EXCHANGE_LENGTH = 128
_HOLDINGS_DATE_LABELS = frozenset(
    {"fund holdings as of", "holdings as of", "as of"}
)

SOXX_ETF = InstrumentDTO(
    symbol="SOXX",
    name="iShares Semiconductor ETF",
    market="us_stock",
    exchange="NASDAQ",
    currency="USD",
    timezone="America/New_York",
    instrument_type="etf",
    provider_symbol="SOXX",
)


class IsharesSoxxUniverseProvider:
    """Fetch one fully validated current snapshot, not historical membership."""

    def __init__(
        self,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        proxy_url: str | None = None,
    ) -> None:
        self._request_timeout_seconds = validate_request_timeout(
            request_timeout_seconds
        )
        self._proxy_url = proxy_url

    @property
    def request_timeout_seconds(self) -> float:
        return self._request_timeout_seconds

    @property
    def proxy_url(self) -> str | None:
        return self._proxy_url

    def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
        if universe_code != "soxx":
            raise ProviderCompatibilityError(
                "iShares universe provider supports soxx only"
            )
        content = fetch_bytes(
            SOXX_HOLDINGS_URL,
            max_bytes=SOXX_MAX_BYTES,
            timeout=self._request_timeout_seconds,
            expected_content_type=("text/csv", "text/plain"),
            proxy_url=self._proxy_url,
        )
        return UniverseSnapshot(
            universe_code="soxx",
            source=SOURCE,
            effective_date=_soxx_effective_date(content),
            members=tuple(parse_soxx_holdings(content)),
            related_instruments=(SOXX_ETF,),
        )


def parse_soxx_holdings(content: bytes) -> list[InstrumentDTO]:
    """Locate the real holdings header and retain only Equity asset rows."""
    rows = _csv_rows(content)
    header_index, header = _find_header(rows)
    members: list[InstrumentDTO] = []
    seen_symbols: set[str] = set()
    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            raise ProviderDataInvalid("SOXX holding row has the wrong column count")
        values = dict(zip(header, row, strict=True))
        if values["Asset Class"].strip().casefold() != "equity":
            continue
        member = _equity_instrument(values)
        if member.symbol in seen_symbols:
            raise ProviderDataInvalid(f"Duplicate SOXX constituent ticker: {member.symbol}")
        seen_symbols.add(member.symbol)
        members.append(member)
    if not members:
        raise ProviderDataInvalid("SOXX holdings contain no Equity rows")
    return members


def _csv_rows(content: bytes) -> list[list[str]]:
    if not isinstance(content, bytes) or not content:
        raise ProviderDataInvalid("SOXX holdings CSV is empty")
    try:
        text = content.decode("utf-8-sig")
        return list(csv.reader(StringIO(text, newline="")))
    except (UnicodeDecodeError, csv.Error):
        raise ProviderDataInvalid("SOXX holdings CSV is invalid") from None


def _find_header(rows: list[list[str]]) -> tuple[int, list[str]]:
    for index, raw_row in enumerate(rows):
        row = [cell.strip() for cell in raw_row]
        if tuple(row[:4]) != _REQUIRED_HEADER or "Exchange" not in row[4:]:
            continue
        if len(set(row)) != len(row):
            raise ProviderDataInvalid("SOXX holdings header has duplicate columns")
        return index, row
    raise ProviderDataInvalid("SOXX holdings CSV header is missing")


def _equity_instrument(values: dict[str, str]) -> InstrumentDTO:
    symbol, provider_symbol = _ticker(values["Ticker"])
    return InstrumentDTO(
        symbol=symbol,
        name=_required_text(values["Name"], "name", _MAX_NAME_LENGTH),
        market="us_stock",
        exchange=_required_text(
            values["Exchange"], "exchange", _MAX_EXCHANGE_LENGTH
        ).upper(),
        currency="USD",
        timezone="America/New_York",
        instrument_type="stock",
        provider_symbol=provider_symbol,
    )


def _ticker(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ProviderDataInvalid("SOXX equity ticker is invalid")
    normalized = value.strip().upper()
    if (
        len(normalized) > _MAX_TICKER_LENGTH
        or _TICKER_PATTERN.fullmatch(normalized) is None
    ):
        raise ProviderDataInvalid("SOXX equity ticker is invalid")
    canonical = normalized.replace("-", ".").replace("/", ".")
    yahoo = normalized.replace(".", "-").replace("/", "-")
    return canonical, yahoo


def _required_text(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str) or any(ord(character) < 32 for character in value):
        raise ProviderDataInvalid(f"SOXX equity {field} is invalid")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > max_length:
        raise ProviderDataInvalid(f"SOXX equity {field} is invalid")
    return normalized


def _soxx_effective_date(content: bytes) -> date | None:
    rows = _csv_rows(content)
    dates: set[date] = set()
    for row in rows:
        if not row or row[0].strip().casefold() not in _HOLDINGS_DATE_LABELS:
            continue
        value = row[1] if len(row) > 1 else None
        dates.add(_parse_effective_date(value))
    if len(dates) > 1:
        raise ProviderDataInvalid("iShares effective date is ambiguous")
    return next(iter(dates), None)


def _parse_effective_date(value: object) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ProviderDataInvalid("iShares effective date is invalid")
    text = " ".join(value.split())
    for date_format in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise ProviderDataInvalid("iShares effective date is invalid")
