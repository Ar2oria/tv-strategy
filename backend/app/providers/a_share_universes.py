"""Current A-share universe snapshots from documented AKShare readers."""

import logging
import re
from collections.abc import Mapping
from datetime import date
from types import MappingProxyType

import akshare as ak

from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderError,
    ProviderUnavailable,
)
from app.providers.ohlcv_normalization import normalize_date, records_from_frame
from app.providers.sdk_runtime import provider_runtime
from app.providers.timeouts import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    validate_request_timeout,
)

logger = logging.getLogger(__name__)
SOURCE = "akshare"
CSI300_CODE = "000300"

CSI300_INDEX = InstrumentDTO(
    symbol="000300.SH",
    name="CSI 300 Index",
    market="a_share",
    exchange="SSE",
    currency="CNY",
    timezone="Asia/Shanghai",
    instrument_type="index",
    provider_symbol=CSI300_CODE,
)

_EXCHANGES = MappingProxyType(
    {
        "sh": ("SH", "SSE"),
        "sse": ("SH", "SSE"),
        "shse": ("SH", "SSE"),
        "xshg": ("SH", "SSE"),
        "shanghai stock exchange": ("SH", "SSE"),
        "上海": ("SH", "SSE"),
        "上海证券交易所": ("SH", "SSE"),
        "sz": ("SZ", "SZSE"),
        "szse": ("SZ", "SZSE"),
        "shenzhen stock exchange": ("SZ", "SZSE"),
        "深圳": ("SZ", "SZSE"),
        "深圳证券交易所": ("SZ", "SZSE"),
    }
)
_SHANGHAI_PREFIXES = ("600", "601", "603", "605", "688", "689")
_SHENZHEN_PREFIXES = ("000", "001", "002", "003", "30")


class AkshareUniverseProvider:
    """Fetch and fully validate one current A-share universe before returning it."""

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
        if universe_code == "csi300":
            frame = _request(
                "index_stock_cons_csindex",
                proxy_url=self._proxy_url,
                symbol=CSI300_CODE,
            )
            return _csi300_snapshot(frame)
        if universe_code == "star_market":
            frame = _request(
                "stock_info_sh_name_code",
                proxy_url=self._proxy_url,
                symbol="科创板",
            )
            return _board_snapshot(frame, universe_code)
        if universe_code == "chinext":
            frame = _request(
                "stock_info_sz_name_code",
                proxy_url=self._proxy_url,
                symbol="A股列表",
            )
            return _board_snapshot(frame, universe_code)
        raise ProviderCompatibilityError(
            "AKShare universe provider supports csi300, star_market, and chinext only"
        )


def _request(
    reader_name: str,
    *,
    proxy_url: str | None = None,
    **kwargs: object,
) -> object:
    try:
        reader = getattr(ak, reader_name)
        with provider_runtime("akshare", proxy_url, wait=True):
            return reader(**kwargs)
    except ProviderError:
        raise
    except Exception as error:
        logger.warning("AKShare universe reader failed: %s", reader_name)
        raise ProviderUnavailable() from error


def _csi300_snapshot(frame: object) -> UniverseSnapshot:
    rows = records_from_frame(frame)
    if not rows:
        raise ProviderDataInvalid("AKShare csi300 constituent list is empty")
    members = tuple(_csi300_member(row) for row in rows)
    _require_unique_nonempty(members, "csi300")
    effective_date = _single_effective_date(rows)
    return UniverseSnapshot(
        universe_code="csi300",
        source=SOURCE,
        effective_date=effective_date,
        members=members,
        related_instruments=(CSI300_INDEX,),
    )


def _board_snapshot(frame: object, universe_code: str) -> UniverseSnapshot:
    rows = records_from_frame(frame)
    if not rows:
        raise ProviderDataInvalid(f"AKShare {universe_code} list is empty")
    members = tuple(_board_members(rows, universe_code))
    _require_unique_nonempty(members, universe_code)
    return UniverseSnapshot(
        universe_code=universe_code,
        source=SOURCE,
        effective_date=None,
        members=members,
    )


def _csi300_member(row: Mapping[str, object]) -> InstrumentDTO:
    code = _code(_required(row, "成分券代码"))
    name = _name(_required(row, "成分券名称"))
    suffix, exchange = _exchange(_required(row, "交易所"))
    if not _code_matches_exchange(code, suffix):
        raise ProviderDataInvalid(
            f"A-share code {code} is inconsistent with exchange {exchange}"
        )
    return _instrument(code, name, suffix, exchange)


def _board_members(
    rows: list[Mapping[str, object]], universe_code: str
) -> list[InstrumentDTO]:
    members: list[InstrumentDTO] = []
    for row in rows:
        code_column, name_column = _board_columns(row, universe_code)
        code = _code(_required(row, code_column))
        if universe_code == "chinext" and not code.startswith("30"):
            continue
        if universe_code == "star_market" and not code.startswith("68"):
            raise ProviderDataInvalid("Shanghai STAR list contains a non-STAR code")
        name = _name(_required(row, name_column))
        suffix, exchange = (
            ("SH", "SSE") if universe_code == "star_market" else ("SZ", "SZSE")
        )
        members.append(_instrument(code, name, suffix, exchange))
    return members


def _board_columns(
    row: Mapping[str, object], universe_code: str
) -> tuple[str, str]:
    if universe_code == "star_market":
        return "证券代码", "证券简称"
    if "A股代码" in row or "A股简称" in row:
        return "A股代码", "A股简称"
    return "证券代码", "证券简称"


def _instrument(
    code: str, name: str, suffix: str, exchange: str
) -> InstrumentDTO:
    return InstrumentDTO(
        symbol=f"{code}.{suffix}",
        name=name,
        market="a_share",
        exchange=exchange,
        currency="CNY",
        timezone="Asia/Shanghai",
        instrument_type="stock",
        provider_symbol=code,
    )


def _required(row: Mapping[str, object], column: str) -> object:
    try:
        return row[column]
    except KeyError:
        raise ProviderDataInvalid(f"AKShare row is missing {column}") from None


def _code(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderDataInvalid("A-share constituent code must be six digits")
    code = value.strip()
    if re.fullmatch(r"\d{6}", code) is None:
        raise ProviderDataInvalid("A-share constituent code must be six digits")
    return code


def _name(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderDataInvalid("A-share constituent name is invalid")
    name = " ".join(value.split())
    if not name:
        raise ProviderDataInvalid("A-share constituent name is invalid")
    return name


def _exchange(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ProviderDataInvalid("A-share exchange is invalid")
    normalized = " ".join(value.split()).casefold()
    try:
        return _EXCHANGES[normalized]
    except KeyError:
        raise ProviderDataInvalid("A-share exchange is not SH or SZ") from None


def _code_matches_exchange(code: str, suffix: str) -> bool:
    prefixes = _SHANGHAI_PREFIXES if suffix == "SH" else _SHENZHEN_PREFIXES
    return code.startswith(prefixes)


def _single_effective_date(rows: list[Mapping[str, object]]) -> date:
    dates = {normalize_date(_required(row, "日期")) for row in rows}
    if len(dates) != 1:
        raise ProviderDataInvalid("CSI300 constituent effective date is ambiguous")
    return next(iter(dates))


def _require_unique_nonempty(
    members: tuple[InstrumentDTO, ...], universe_code: str
) -> None:
    if not members:
        raise ProviderDataInvalid(f"AKShare {universe_code} list is empty after filtering")
    symbols = [item.symbol for item in members]
    if len(set(symbols)) != len(symbols):
        raise ProviderDataInvalid(f"Duplicate {universe_code} constituent symbol")
