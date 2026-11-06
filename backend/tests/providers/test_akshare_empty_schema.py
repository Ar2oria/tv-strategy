"""AKShare empty-schema and requested-range regressions for every route."""

from dataclasses import dataclass, replace
from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest

import app.providers.akshare_ohlcv as adapter
from app.domain.dto import InstrumentDTO
from app.providers.errors import ProviderDataInvalid

CHINESE = ("日期", "开盘", "最高", "最低", "收盘", "成交量")
HSTECH_COLUMNS = ("date", "open", "high", "low", "latest")
A_STOCK = InstrumentDTO(
    symbol="600000.SH",
    name="Pudong Development Bank",
    market="a_share",
    exchange="SSE",
    currency="CNY",
    timezone="Asia/Shanghai",
    instrument_type="stock",
    provider_symbol="600000",
)


@dataclass(frozen=True)
class Route:
    name: str
    reader: str
    instrument: InstrumentDTO
    adjustment: str
    columns: tuple[str, ...]


ROUTES = (
    Route("a-stock", "stock_zh_a_hist", A_STOCK, "qfq", CHINESE),
    Route(
        "a-index",
        "index_zh_a_hist",
        replace(A_STOCK, instrument_type="index", provider_symbol="000300"),
        "none",
        CHINESE,
    ),
    Route(
        "hk-stock",
        "stock_hk_hist",
        replace(
            A_STOCK,
            symbol="0700.HK",
            market="hk_stock",
            exchange="HKEX",
            currency="HKD",
            timezone="Asia/Hong_Kong",
            provider_symbol="00700",
        ),
        "qfq",
        CHINESE,
    ),
    Route(
        "hstech",
        "stock_hk_index_daily_em",
        replace(
            A_STOCK,
            symbol="HSTECH.HK",
            market="hk_stock",
            exchange="HKEX",
            currency="HKD",
            timezone="Asia/Hong_Kong",
            instrument_type="index",
            provider_symbol="HSTECH.HK",
        ),
        "none",
        HSTECH_COLUMNS,
    ),
)


def fetch(route: Route) -> list[object]:
    return adapter.AkshareOhlcvProvider().fetch_daily(
        route.instrument,
        date(2026, 1, 2),
        date(2026, 1, 3),
        route.adjustment,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
@pytest.mark.parametrize("schema", ["zero-columns", "complete-empty"])
def test_genuine_or_complete_empty_frames_are_valid(
    monkeypatch: pytest.MonkeyPatch,
    route: Route,
    schema: str,
) -> None:
    columns = () if schema == "zero-columns" else route.columns
    monkeypatch.setattr(
        adapter.ak,
        route.reader,
        Mock(return_value=pd.DataFrame(columns=columns)),
    )

    assert fetch(route) == []


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
@pytest.mark.parametrize("schema", ["partial", "duplicate"])
def test_empty_frames_with_malformed_columns_fail_visibly(
    monkeypatch: pytest.MonkeyPatch,
    route: Route,
    schema: str,
) -> None:
    columns = (
        route.columns[:2]
        if schema == "partial"
        else (route.columns[0], *route.columns)
    )
    monkeypatch.setattr(
        adapter.ak,
        route.reader,
        Mock(return_value=pd.DataFrame(columns=columns)),
    )

    with pytest.raises(ProviderDataInvalid, match="columns"):
        fetch(route)


@pytest.mark.parametrize("route", [ROUTES[0], ROUTES[3]], ids=["a-stock", "hstech"])
@pytest.mark.parametrize("bad_day", [date(2026, 1, 1), date(2026, 1, 4)])
def test_out_of_range_akshare_rows_are_rejected_not_filtered(
    monkeypatch: pytest.MonkeyPatch,
    route: Route,
    bad_day: date,
) -> None:
    def row(day: date) -> dict[str, object]:
        if route.columns == CHINESE:
            return {
                "日期": day.isoformat(),
                "开盘": 10.0,
                "最高": 12.0,
                "最低": 9.0,
                "收盘": 11.0,
                "成交量": 100.0,
            }
        return {
            "date": day.isoformat(),
            "open": 10.0,
            "high": 12.0,
            "low": 9.0,
            "latest": 11.0,
        }

    monkeypatch.setattr(
        adapter.ak,
        route.reader,
        Mock(return_value=pd.DataFrame([row(date(2026, 1, 2)), row(bad_day)])),
    )

    with pytest.raises(ProviderDataInvalid, match="range"):
        fetch(route)
