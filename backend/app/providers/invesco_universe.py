"""Bounded Invesco QQQ holdings adapter for the current Nasdaq-100 snapshot."""

import json
import re
from collections.abc import Mapping
from datetime import date, datetime

from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.providers.errors import ProviderCompatibilityError, ProviderDataInvalid
from app.providers.http import fetch_bytes
from app.providers.timeouts import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    validate_request_timeout,
)

QQQ_HOLDINGS_URL = (
    "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/"
    "holdings/fund?idType=ticker&interval=monthly&productType=ETF"
)
SOURCE = "invesco"
QQQ_MAX_BYTES = 4 * 1024 * 1024
QQQ_TIMEOUT_SECONDS = DEFAULT_REQUEST_TIMEOUT_SECONDS
_EQUITY_TYPES = frozenset({"COM", "ADR", "DRNY"})
_NON_EQUITY_TYPES = frozenset({"CURR", "CURRCOL", "IFUT", "SYN"})
_TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*")
_MAX_TICKER_LENGTH = 32
_MAX_NAME_LENGTH = 256

NASDAQ100_INDEX = InstrumentDTO(
    symbol="^NDX",
    name="Nasdaq-100 Index",
    market="us_stock",
    exchange="NASDAQ",
    currency="USD",
    timezone="America/New_York",
    instrument_type="index",
    provider_symbol="^NDX",
)


class InvescoUniverseProvider:
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
        if universe_code != "nasdaq100":
            raise ProviderCompatibilityError(
                "Invesco universe provider supports nasdaq100 only"
            )
        content = fetch_bytes(
            QQQ_HOLDINGS_URL,
            max_bytes=QQQ_MAX_BYTES,
            timeout=self._request_timeout_seconds,
            expected_content_type=("application/json", "text/plain"),
            proxy_url=self._proxy_url,
        )
        payload = _decode_payload(content)
        rows = _holding_rows(payload)
        effective_date = _qqq_effective_date(payload, rows)
        return UniverseSnapshot(
            universe_code="nasdaq100",
            source=SOURCE,
            effective_date=effective_date,
            members=tuple(parse_qqq_holdings(payload)),
            related_instruments=(NASDAQ100_INDEX,),
        )


def parse_qqq_holdings(payload: dict) -> list[InstrumentDTO]:
    """Keep verified equity rows and reject unknown or incomplete schemas."""
    rows = _holding_rows(payload)
    _qqq_effective_date(payload, rows)
    members: list[InstrumentDTO] = []
    seen_symbols: set[str] = set()
    for row in rows:
        security_type = _security_type(row)
        if security_type in _NON_EQUITY_TYPES:
            continue
        member = _equity_instrument(row)
        if member.symbol in seen_symbols:
            raise ProviderDataInvalid(
                f"Duplicate Invesco constituent ticker: {member.symbol}"
            )
        seen_symbols.add(member.symbol)
        members.append(member)
    if not members:
        raise ProviderDataInvalid("Invesco QQQ holdings contain no equities")
    return members


def _decode_payload(content: bytes) -> dict:
    if not content:
        raise ProviderDataInvalid("Invesco QQQ holdings response is empty")
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderDataInvalid("Invesco QQQ holdings JSON is invalid") from None
    if not isinstance(payload, dict):
        raise ProviderDataInvalid("Invesco QQQ holdings root must be an object")
    return payload


def _holding_rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, dict):
        raise ProviderDataInvalid("Invesco QQQ holdings root must be an object")
    rows = payload.get("holdings")
    if not isinstance(rows, list) or not rows:
        raise ProviderDataInvalid("Invesco QQQ holdings list is empty or missing")
    if any(not isinstance(row, Mapping) for row in rows):
        raise ProviderDataInvalid("Every Invesco holding must be an object")
    return rows


def _security_type(row: Mapping[str, object]) -> str:
    value = row.get("securityTypeCode")
    if not isinstance(value, str) or not value.strip():
        raise ProviderDataInvalid("Invesco security type is invalid")
    security_type = value.strip().upper()
    if security_type not in _EQUITY_TYPES | _NON_EQUITY_TYPES:
        raise ProviderDataInvalid(
            f"Unknown Invesco security type: {security_type}"
        )
    return security_type


def _equity_instrument(row: Mapping[str, object]) -> InstrumentDTO:
    symbol, provider_symbol = _ticker(row.get("ticker"))
    return InstrumentDTO(
        symbol=symbol,
        name=_name(row),
        market="us_stock",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        instrument_type="stock",
        provider_symbol=provider_symbol,
    )


def _ticker(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ProviderDataInvalid("Invesco equity ticker is invalid")
    normalized = value.strip().upper()
    if (
        len(normalized) > _MAX_TICKER_LENGTH
        or _TICKER_PATTERN.fullmatch(normalized) is None
    ):
        raise ProviderDataInvalid("Invesco equity ticker is invalid")
    canonical = normalized.replace("-", ".").replace("/", ".")
    yahoo = normalized.replace(".", "-").replace("/", "-")
    return canonical, yahoo


def _name(row: Mapping[str, object]) -> str:
    value = row.get("name")
    if value is None:
        value = row.get("securityName")
    if value is None:
        value = row.get("issuerName")
    if not isinstance(value, str):
        raise ProviderDataInvalid("Invesco equity name is invalid")
    if any(ord(character) < 32 for character in value):
        raise ProviderDataInvalid("Invesco equity name is invalid")
    name = " ".join(value.split())
    if not name or len(name) > _MAX_NAME_LENGTH:
        raise ProviderDataInvalid("Invesco equity name is invalid")
    return name


def _qqq_effective_date(
    payload: Mapping[str, object], rows: list[Mapping[str, object]]
) -> date:
    top_level = (
        _parse_effective_date(payload["effectiveDate"])
        if "effectiveDate" in payload
        else None
    )
    dates: set[date] = set()
    for row in rows:
        if "effectiveDate" in row:
            dates.add(_parse_effective_date(row["effectiveDate"]))
        elif top_level is not None:
            dates.add(top_level)
        else:
            raise ProviderDataInvalid("Invesco effective date is missing")
    if top_level is not None:
        dates.add(top_level)
    if len(dates) != 1:
        raise ProviderDataInvalid("Invesco effective date is missing or ambiguous")
    return next(iter(dates))


def _parse_effective_date(value: object) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ProviderDataInvalid("Invesco effective date is invalid")
    text = value.strip()
    for date_format in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        raise ProviderDataInvalid("Invesco effective date is invalid") from None
