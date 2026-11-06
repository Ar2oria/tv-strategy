"""Offline SDK translation tests for AKShare daily OHLCV bars."""

from dataclasses import replace
from datetime import date, datetime
from unittest.mock import Mock

import pandas as pd
import pytest

import app.providers.akshare_ohlcv as adapter
from app.domain.dto import BarDTO, InstrumentDTO
from app.providers.base import OhlcvProvider
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderUnavailable,
)

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


def instrument(**changes: object) -> InstrumentDTO:
    return replace(A_STOCK, **changes)


def chinese_rows() -> list[dict[str, object]]:
    return [
        {
            "日期": "2026-01-03",
            "开盘": 11.0,
            "最高": 13.0,
            "最低": 10.0,
            "收盘": 12.0,
            "成交量": 2000,
        },
        {
            "日期": "2026-01-02",
            "开盘": 9.0,
            "最高": 12.0,
            "最低": 8.0,
            "收盘": 11.0,
            "成交量": 1000,
        },
    ]


def expected_bars(
    adjustment: str = "qfq", volume_multiplier: float = 1.0
) -> list[BarDTO]:
    return [
        BarDTO(
            time=date(2026, 1, 2),
            open=9.0,
            high=12.0,
            low=8.0,
            close=11.0,
            volume=1000.0 * volume_multiplier,
            source="akshare",
            adjustment=adjustment,  # type: ignore[arg-type]
        ),
        BarDTO(
            time=date(2026, 1, 3),
            open=11.0,
            high=13.0,
            low=10.0,
            close=12.0,
            volume=2000.0 * volume_multiplier,
            source="akshare",
            adjustment=adjustment,  # type: ignore[arg-type]
        ),
    ]


def test_a_share_stock_uses_qfq_maps_chinese_columns_and_converts_lots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = Mock(return_value=pd.DataFrame(chinese_rows()))
    monkeypatch.setattr(adapter.ak, "stock_zh_a_hist", call)

    result = adapter.AkshareOhlcvProvider().fetch_daily(
        A_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
    )

    call.assert_called_once_with(
        symbol="600000",
        period="daily",
        start_date="20260102",
        end_date="20260103",
        adjust="qfq",
    )
    assert result == expected_bars(volume_multiplier=100.0)
    assert isinstance(adapter.AkshareOhlcvProvider(), OhlcvProvider)


@pytest.mark.parametrize("provider_symbol", ["00700", "0700", "0700.HK"])
def test_hk_stock_uses_qfq_normalizes_code_and_keeps_share_volume_unscaled(
    monkeypatch: pytest.MonkeyPatch, provider_symbol: str
) -> None:
    call = Mock(return_value=pd.DataFrame(chinese_rows()))
    monkeypatch.setattr(adapter.ak, "stock_hk_hist", call)
    hk_stock = instrument(
        symbol="0700.HK",
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        provider_symbol=provider_symbol,
    )

    result = adapter.AkshareOhlcvProvider().fetch_daily(
        hk_stock, date(2026, 1, 2), date(2026, 1, 3), "qfq"
    )

    call.assert_called_once_with(
        symbol="00700",
        period="daily",
        start_date="20260102",
        end_date="20260103",
        adjust="qfq",
    )
    assert result == expected_bars()


def test_a_share_index_uses_no_adjustment_and_converts_lots_to_shares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = Mock(return_value=pd.DataFrame(chinese_rows()))
    monkeypatch.setattr(adapter.ak, "index_zh_a_hist", call)
    csi300 = instrument(
        symbol="000300.SH",
        instrument_type="index",
        provider_symbol="000300",
    )

    result = adapter.AkshareOhlcvProvider().fetch_daily(
        csi300, date(2026, 1, 2), date(2026, 1, 3), "none"
    )

    call.assert_called_once_with(
        symbol="000300",
        period="daily",
        start_date="20260102",
        end_date="20260103",
    )
    assert result == expected_bars("none", volume_multiplier=100.0)


def test_hstech_maps_latest_to_close_and_keeps_volume_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-01-03", "open": 11, "high": 13, "low": 10, "latest": 12},
            {"date": datetime(2026, 1, 2), "open": 9, "high": 12, "low": 8, "latest": 11},
        ]
    )
    call = Mock(return_value=frame)
    monkeypatch.setattr(adapter.ak, "stock_hk_index_daily_em", call)
    hstech = instrument(
        symbol="HSTECH.HK",
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        instrument_type="index",
        provider_symbol="HSTECH.HK",
    )

    result = adapter.AkshareOhlcvProvider().fetch_daily(
        hstech, date(2026, 1, 2), date(2026, 1, 3), "none"
    )

    call.assert_called_once_with(symbol="HSTECH")
    assert [(row.time, row.close, row.volume) for row in result] == [
        (date(2026, 1, 2), 11.0, None),
        (date(2026, 1, 3), 12.0, None),
    ]
    assert all(row.source == "akshare" and row.adjustment == "none" for row in result)


def test_hstech_invalid_out_of_range_row_fails_before_range_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            {"date": "2026-01-02", "open": 9, "high": 12, "low": 8, "latest": 11},
            {
                "date": "2026-01-01",
                "open": 7,
                "high": 9,
                "low": 6,
                "latest": float("nan"),
            },
        ]
    )
    monkeypatch.setattr(
        adapter.ak, "stock_hk_index_daily_em", Mock(return_value=frame)
    )
    hstech = instrument(
        symbol="HSTECH.HK",
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        instrument_type="index",
        provider_symbol="HSTECH",
    )

    with pytest.raises(ProviderDataInvalid):
        adapter.AkshareOhlcvProvider().fetch_daily(
            hstech, date(2026, 1, 2), date(2026, 1, 3), "none"
        )


def test_none_start_uses_documented_full_history_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = Mock(return_value=pd.DataFrame())
    monkeypatch.setattr(adapter.ak, "stock_zh_a_hist", call)

    assert adapter.AkshareOhlcvProvider().fetch_daily(
        A_STOCK, None, date(2026, 1, 3), "qfq"
    ) == []
    assert call.call_args.kwargs["start_date"] == "19700101"


@pytest.mark.parametrize("field", ["开盘", "最高", "最低", "收盘", "成交量"])
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), None, ""])
def test_nan_or_missing_numeric_values_raise_instead_of_dropping_rows(
    monkeypatch: pytest.MonkeyPatch, field: str, bad_value: object
) -> None:
    rows = chinese_rows()
    rows[0][field] = bad_value
    monkeypatch.setattr(
        adapter.ak, "stock_zh_a_hist", Mock(return_value=pd.DataFrame(rows))
    )

    with pytest.raises(ProviderDataInvalid):
        adapter.AkshareOhlcvProvider().fetch_daily(
            A_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
        )


@pytest.mark.parametrize(
    "rows",
    [
        [{"日期": "not-a-date", "开盘": 9, "最高": 12, "最低": 8, "收盘": 11, "成交量": 1}],
        [{"开盘": 9, "最高": 12, "最低": 8, "收盘": 11, "成交量": 1}],
        [{"日期": "2026-01-02", "开盘": 13, "最高": 12, "最低": 8, "收盘": 11, "成交量": 1}],
        chinese_rows() + [chinese_rows()[0]],
    ],
    ids=["bad-date", "missing-date", "bad-ohlc", "duplicate-date"],
)
def test_malformed_rows_fail_the_complete_response(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]]
) -> None:
    monkeypatch.setattr(
        adapter.ak, "stock_zh_a_hist", Mock(return_value=pd.DataFrame(rows))
    )

    with pytest.raises(ProviderDataInvalid):
        adapter.AkshareOhlcvProvider().fetch_daily(
            A_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
        )


@pytest.mark.parametrize(
    ("candidate", "adjustment"),
    [
        (A_STOCK, "none"),
        (instrument(instrument_type="index"), "qfq"),
        (instrument(market="hk_stock"), "none"),
        (instrument(market="hk_stock", instrument_type="index"), "qfq"),
        (instrument(market="us_stock"), "qfq"),
        (instrument(instrument_type="etf"), "qfq"),
        (
            instrument(
                symbol="HSI.HK",
                market="hk_stock",
                instrument_type="index",
                provider_symbol="HSI",
            ),
            "none",
        ),
    ],
    ids=[
        "unadjusted-stock",
        "adjusted-index",
        "unadjusted-hk-stock",
        "adjusted-hk-index",
        "wrong-market",
        "unsupported-etf",
        "unsupported-hk-index",
    ],
)
def test_unsupported_combinations_fail_before_any_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
    candidate: InstrumentDTO,
    adjustment: str,
) -> None:
    calls = [Mock() for _ in range(4)]
    for name, call in zip(
        (
            "stock_zh_a_hist",
            "stock_hk_hist",
            "index_zh_a_hist",
            "stock_hk_index_daily_em",
        ),
        calls,
        strict=True,
    ):
        monkeypatch.setattr(adapter.ak, name, call)

    with pytest.raises(ProviderCompatibilityError):
        adapter.AkshareOhlcvProvider().fetch_daily(
            candidate, date(2026, 1, 2), date(2026, 1, 3), adjustment  # type: ignore[arg-type]
        )
    assert all(call.call_count == 0 for call in calls)


@pytest.mark.parametrize("symbol", ["600000 OR 1=1", "", "60000", "6000000"])
def test_invalid_a_share_symbols_fail_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch, symbol: str
) -> None:
    call = Mock()
    monkeypatch.setattr(adapter.ak, "stock_zh_a_hist", call)

    with pytest.raises(ProviderDataInvalid):
        adapter.AkshareOhlcvProvider().fetch_daily(
            instrument(provider_symbol=symbol),
            date(2026, 1, 2),
            date(2026, 1, 3),
            "qfq",
        )
    call.assert_not_called()


def test_upstream_failure_and_invalid_range_use_typed_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter.ak, "stock_zh_a_hist", Mock(side_effect=RuntimeError("secret upstream"))
    )
    provider = adapter.AkshareOhlcvProvider()

    with pytest.raises(ProviderUnavailable) as error:
        provider.fetch_daily(A_STOCK, None, date(2026, 1, 3), "qfq")
    assert "secret upstream" not in str(error.value)
    with pytest.raises(ProviderDataInvalid):
        provider.fetch_daily(
            A_STOCK, date(2026, 1, 4), date(2026, 1, 3), "qfq"
        )
