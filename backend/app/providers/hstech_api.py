"""Bounded, token-authenticated iTiger HSTECH constituent snapshots."""

import json
import re
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlencode

from app.config.itiger_token import default_itiger_token
from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderConfigurationError,
    ProviderDataInvalid,
)
from app.providers.http import fetch_bytes
from app.providers.timeouts import validate_request_timeout

API_URL = "https://hq.skytigris.cn/hkstock/market/index/package_HSTECH"
SOURCE = "itiger"
PAGE_SIZE = 20
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 1024 * 1024
_CODE_PATTERN = re.compile(r"[0-9]{4,5}")
_BASE_PARAMS = {
    "region": "SGP",
    "lang": "zh_CN",
    "deviceId": "web-7571e110-baba-4ce0-ade5-2dda292",
    "appVer": "7.78.5",
    "appName": "web",
    "vendor": "web",
    "platform": "web",
    "size": str(PAGE_SIZE),
    "delay": "false",
}
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Baggage": "tenantId=TBGLOBAL",
    "Cache-Control": "no-cache",
    "Origin": "https://www.itiger.com",
    "Pragma": "no-cache",
    "Referer": "https://www.itiger.com/",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
    ),
}

HSTECH_INDEX = InstrumentDTO(
    symbol="HSTECH.HK",
    name="Hang Seng TECH Index",
    market="hk_stock",
    exchange="HKEX",
    currency="HKD",
    timezone="Asia/Hong_Kong",
    instrument_type="index",
    provider_symbol="HSTECH.HK",
)


class ItigerUniverseProvider:
    """Use only the iTiger constituent API for HSTECH snapshots."""

    def __init__(
        self,
        *,
        request_timeout_seconds: float = 20.0,
        proxy_url: str | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self._request_timeout_seconds = validate_request_timeout(
            request_timeout_seconds
        )
        self._proxy_url = proxy_url
        self._bearer_token = bearer_token or default_itiger_token()

    @property
    def request_timeout_seconds(self) -> float:
        return self._request_timeout_seconds

    @property
    def proxy_url(self) -> str | None:
        return self._proxy_url

    @property
    def bearer_token(self) -> str | None:
        return self._bearer_token

    def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
        if universe_code != "hstech":
            raise ProviderCompatibilityError("iTiger supports hstech only")
        token = self._bearer_token or default_itiger_token()
        if not token:
            raise ProviderConfigurationError("iTiger bearer token is not configured")
        return fetch_hstech_api_snapshot(
            proxy_url=self._proxy_url,
            request_timeout_seconds=self._request_timeout_seconds,
            bearer_token=token,
        )


def fetch_hstech_api_snapshot(
    *,
    proxy_url: str | None,
    request_timeout_seconds: float,
    bearer_token: str,
    now_ms: Callable[[], int] | None = None,
) -> UniverseSnapshot:
    """Fetch every constituent page and reject incomplete or duplicate snapshots."""
    if not isinstance(bearer_token, str) or not bearer_token.strip():
        raise ProviderConfigurationError("iTiger bearer token is not configured")
    timeout = validate_request_timeout(request_timeout_seconds)
    clock = now_ms or (lambda: int(time.time() * 1000))
    token = bearer_token.strip()
    members: list[InstrumentDTO] = []
    seen_symbols: set[str] = set()
    expected_count: int | None = None
    expected_page_count: int | None = None
    for page in range(MAX_PAGES):
        payload = _download_page(page, token, clock, proxy_url, timeout)
        rows, total_count, total_page = _parse_page(payload, page)
        if expected_count is None:
            expected_count = total_count
            expected_page_count = total_page
        elif total_count != expected_count:
            raise ProviderDataInvalid("HSTECH constituent count changed between pages")
        if total_page != expected_page_count:
            raise ProviderDataInvalid("HSTECH totalPage changed between pages")
        for instrument in rows:
            if instrument.symbol in seen_symbols:
                raise ProviderDataInvalid("Duplicate HSTECH constituent symbol")
            seen_symbols.add(instrument.symbol)
            members.append(instrument)
        if page + 1 >= expected_page_count:
            break
        if not rows:
            raise ProviderDataInvalid("HSTECH page is empty before all constituents arrive")
    else:
        raise ProviderDataInvalid("HSTECH pagination page limit exceeded")
    if expected_count is None or len(members) != expected_count:
        raise ProviderDataInvalid("HSTECH constituent count does not match totalCount")
    if not members:
        raise ProviderDataInvalid("HSTECH constituents are empty")
    return UniverseSnapshot(
        universe_code="hstech",
        source=SOURCE,
        effective_date=None,
        members=tuple(members),
        related_instruments=(HSTECH_INDEX,),
    )


def _download_page(
    page: int,
    token: str,
    now_ms: Callable[[], int],
    proxy_url: str | None,
    timeout: float,
) -> object:
    params = {**_BASE_PARAMS, "_s": now_ms(), "page": page}
    headers = {**_HEADERS, "Authorization": f"Bearer {token}"}
    content = fetch_bytes(
        f"{API_URL}?{urlencode(params)}",
        max_bytes=MAX_RESPONSE_BYTES,
        timeout=timeout,
        expected_content_type=("application/json", "text/plain"),
        proxy_url=proxy_url,
        headers=headers,
    )
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderDataInvalid("HSTECH API JSON is invalid") from None


def _parse_page(payload: object, expected_page: int) -> tuple[list[InstrumentDTO], int, int]:
    if not isinstance(payload, Mapping) or payload.get("ret") != 0:
        raise ProviderDataInvalid("HSTECH API returned an unsuccessful response")
    topics = payload.get("topics")
    if not isinstance(topics, list) or len(topics) != 1:
        raise ProviderDataInvalid("HSTECH API topics are missing or ambiguous")
    topic = topics[0]
    if not isinstance(topic, Mapping):
        raise ProviderDataInvalid("HSTECH topic must be an object")
    page = _integer(topic.get("page"), "page")
    total_count = _integer(topic.get("totalCount"), "totalCount")
    total_page = _integer(topic.get("totalPage"), "totalPage")
    if page != expected_page or total_count < 0 or total_page < 1:
        raise ProviderDataInvalid("HSTECH page metadata is inconsistent")
    if total_count > MAX_PAGES * PAGE_SIZE:
        raise ProviderDataInvalid("HSTECH constituent count exceeds the allowed limit")
    rows = topic.get("data")
    if not isinstance(rows, list):
        raise ProviderDataInvalid("HSTECH constituent rows must be a list")
    return (
        [_constituent(row) for row in rows],
        total_count,
        total_page,
    )


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderDataInvalid(f"HSTECH {field} must be an integer")
    return value


def _constituent(row: object) -> InstrumentDTO:
    if not isinstance(row, (list, tuple)) or len(row) < 2:
        raise ProviderDataInvalid("HSTECH constituent row is malformed")
    code, name = row[0], row[1]
    if not isinstance(code, str) or _CODE_PATTERN.fullmatch(code.strip()) is None:
        raise ProviderDataInvalid("HSTECH constituent code is invalid")
    if not isinstance(name, str) or any(ord(character) < 32 for character in name):
        raise ProviderDataInvalid("HSTECH constituent name is invalid")
    normalized_name = " ".join(name.split())
    if not normalized_name or len(normalized_name) > 256:
        raise ProviderDataInvalid("HSTECH constituent name is invalid")
    normalized_code = code.strip().zfill(5)
    yahoo_code = normalized_code[1:] if normalized_code.startswith("0") else normalized_code
    symbol = f"{yahoo_code}.HK"
    return InstrumentDTO(
        symbol=symbol,
        name=normalized_name,
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        instrument_type="stock",
        provider_symbol=symbol,
    )
