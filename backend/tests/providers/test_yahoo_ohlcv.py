"""Offline yfinance translation and symbol-mapping tests."""

from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import Mock

import pandas as pd
import pytest

import app.providers.yahoo_ohlcv as adapter
from app.domain.dto import BarDTO, InstrumentDTO
from app.providers.base import OhlcvProvider
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderUnavailable,
)

US_STOCK = InstrumentDTO(
    symbol="AAPL",
    name="Apple Inc.",
    market="us_stock",
    exchange="NASDAQ",
    currency="USD",
    timezone="America/New_York",
    instrument_type="stock",
    provider_symbol="AAPL",
)


def instrument(**changes: object) -> InstrumentDTO:
    return replace(US_STOCK, **changes)


def history_frame(
    *,
    index: list[object] | None = None,
    close: list[object] | None = None,
) -> pd.DataFrame:
    dates = index or [
        pd.Timestamp("2026-01-03", tz="America/New_York"),
        pd.Timestamp("2026-01-02", tz="America/New_York"),
    ]
    closes = close or [12.0, 11.0]
    return pd.DataFrame(
        {
            "Open": [11.0, 9.0],
            "High": [13.0, 12.0],
            "Low": [10.0, 8.0],
            "Close": closes,
            "Volume": [2000.0, 1000.0],
        },
        index=pd.Index(dates, name="Date"),
    )


def expected_bars(adjustment: str = "qfq") -> list[BarDTO]:
    return [
        BarDTO(
            time=date(2026, 1, 2),
            open=9.0,
            high=12.0,
            low=8.0,
            close=11.0,
            volume=1000.0,
            source="yfinance",
            adjustment=adjustment,  # type: ignore[arg-type]
        ),
        BarDTO(
            time=date(2026, 1, 3),
            open=11.0,
            high=13.0,
            low=10.0,
            close=12.0,
            volume=2000.0,
            source="yfinance",
            adjustment=adjustment,  # type: ignore[arg-type]
        ),
    ]


def patch_history(
    monkeypatch: pytest.MonkeyPatch, frame: object
) -> tuple[Mock, Mock]:
    history = Mock(return_value=frame)
    ticker = Mock()
    ticker.history = history
    constructor = Mock(return_value=ticker)
    monkeypatch.setattr(adapter.yf, "Ticker", constructor)
    return constructor, history


def test_us_stock_adjusts_all_ohlc_and_uses_inclusive_end_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor, history = patch_history(monkeypatch, history_frame())

    result = adapter.YahooOhlcvProvider().fetch_daily(
        US_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
    )

    constructor.assert_called_once_with("AAPL")
    history.assert_called_once_with(
        interval="1d",
        start="2026-01-02",
        end="2026-01-04",
        auto_adjust=True,
        timeout=20.0,
    )
    assert result == expected_bars()
    assert isinstance(adapter.YahooOhlcvProvider(), OhlcvProvider)


def test_us_etf_is_adjusted_and_share_class_uses_yahoo_dash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor, history = patch_history(monkeypatch, pd.DataFrame())
    etf = instrument(
        symbol="BRK.B",
        name="Berkshire Hathaway Class B",
        instrument_type="etf",
        provider_symbol="BRK.B",
    )

    assert adapter.YahooOhlcvProvider().fetch_daily(
        etf, date(2026, 1, 2), date(2026, 1, 3), "qfq"
    ) == []
    constructor.assert_called_once_with("BRK-B")
    assert history.call_args.kwargs["auto_adjust"] is True
    assert "threads" not in history.call_args.kwargs
    assert "progress" not in history.call_args.kwargs


@pytest.mark.parametrize("provider_symbol", ["0700.HK", "00700.HK", "700", "00700"])
def test_hk_stock_has_explicit_four_digit_yahoo_symbol(
    monkeypatch: pytest.MonkeyPatch, provider_symbol: str
) -> None:
    constructor, history = patch_history(monkeypatch, history_frame())
    hk_stock = instrument(
        symbol="0700.HK",
        name="Tencent Holdings",
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        provider_symbol=provider_symbol,
    )

    result = adapter.YahooOhlcvProvider().fetch_daily(
        hk_stock, date(2026, 1, 2), date(2026, 1, 3), "qfq"
    )

    constructor.assert_called_once_with("0700.HK")
    assert history.call_args.kwargs["auto_adjust"] is True
    assert result == expected_bars()


@pytest.mark.parametrize(
    ("candidate", "yahoo_symbol"),
    [
        (
            instrument(instrument_type="index", provider_symbol="^NDX"),
            "^NDX",
        ),
        (
            instrument(
                symbol="HSTECH.HK",
                name="Hang Seng TECH Index",
                market="hk_stock",
                exchange="HKEX",
                currency="HKD",
                timezone="Asia/Hong_Kong",
                instrument_type="index",
                provider_symbol="HSTECH.HK",
            ),
            "HSTECH.HK",
        ),
    ],
    ids=["nasdaq100", "hstech"],
)
def test_indices_are_unadjusted_and_keep_explicit_yahoo_symbols(
    monkeypatch: pytest.MonkeyPatch,
    candidate: InstrumentDTO,
    yahoo_symbol: str,
) -> None:
    constructor, history = patch_history(monkeypatch, history_frame())

    result = adapter.YahooOhlcvProvider().fetch_daily(
        candidate, date(2026, 1, 2), date(2026, 1, 3), "none"
    )

    constructor.assert_called_once_with(yahoo_symbol)
    assert history.call_args.kwargs["auto_adjust"] is False
    assert result == expected_bars("none")


def test_timezone_aware_index_dates_do_not_shift_through_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = history_frame(
        index=[
            pd.Timestamp("2026-01-03 00:00:00+08:00"),
            pd.Timestamp("2026-01-02 23:00:00-05:00"),
        ]
    )
    patch_history(monkeypatch, frame)
    hstech = instrument(
        symbol="HSTECH.HK",
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        instrument_type="index",
        provider_symbol="HSTECH.HK",
    )

    result = adapter.YahooOhlcvProvider().fetch_daily(
        hstech, date(2026, 1, 2), date(2026, 1, 3), "none"
    )

    assert [row.time for row in result] == [date(2026, 1, 2), date(2026, 1, 3)]


def test_none_start_requests_full_history_and_empty_valid_history_is_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, history = patch_history(monkeypatch, pd.DataFrame())

    assert adapter.YahooOhlcvProvider().fetch_daily(
        US_STOCK, None, date(2026, 1, 3), "qfq"
    ) == []
    assert history.call_args.kwargs["start"] == adapter.FULL_HISTORY_START.isoformat()
    assert history.call_args.kwargs["end"] == (
        date(2026, 1, 3) + timedelta(days=1)
    ).isoformat()


@pytest.mark.parametrize("field", ["Open", "High", "Low", "Close", "Volume"])
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), None])
def test_non_finite_or_missing_numeric_values_fail_complete_response(
    monkeypatch: pytest.MonkeyPatch, field: str, bad_value: object
) -> None:
    frame = history_frame()
    frame.loc[frame.index[0], field] = bad_value
    patch_history(monkeypatch, frame)

    with pytest.raises(ProviderDataInvalid):
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
        )


@pytest.mark.parametrize(
    "frame",
    [
        history_frame(close=[14.0, 11.0]),
        history_frame(index=[date(2026, 1, 2), date(2026, 1, 2)]),
        history_frame(index=["not-a-date", "2026-01-02"]),
        history_frame().drop(columns=["Close"]),
    ],
    ids=["bad-ohlc", "duplicate-date", "bad-date", "missing-column"],
)
def test_malformed_history_fails_visibly(
    monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame
) -> None:
    patch_history(monkeypatch, frame)

    with pytest.raises(ProviderDataInvalid):
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
        )


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(columns=["Open"]),
        pd.DataFrame(
            columns=["Open", "Open", "High", "Low", "Close", "Volume"]
        ),
    ],
    ids=["partial-schema", "duplicate-column"],
)
def test_empty_history_with_columns_requires_unique_complete_schema(
    monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame
) -> None:
    patch_history(monkeypatch, frame)

    with pytest.raises(ProviderDataInvalid):
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
        )


def test_empty_history_with_complete_schema_remains_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    patch_history(monkeypatch, frame)

    assert adapter.YahooOhlcvProvider().fetch_daily(
        US_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
    ) == []


def test_non_dataframe_history_is_not_treated_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_history(monkeypatch, {"Open": []})

    with pytest.raises(ProviderDataInvalid):
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
        )


def test_sdk_failure_is_sanitized_and_invalid_range_needs_no_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor, _ = patch_history(monkeypatch, pd.DataFrame())
    constructor.return_value.history.side_effect = RuntimeError("private upstream detail")

    with pytest.raises(ProviderUnavailable) as captured:
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
        )
    assert "private upstream detail" not in str(captured.value)
    constructor.reset_mock()
    with pytest.raises(ProviderDataInvalid):
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 4), date(2026, 1, 3), "qfq"
        )
    constructor.assert_not_called()


@pytest.mark.parametrize(
    ("candidate", "adjustment"),
    [
        (US_STOCK, "none"),
        (instrument(instrument_type="etf"), "none"),
        (instrument(instrument_type="index", provider_symbol="^NDX"), "qfq"),
        (instrument(market="a_share"), "qfq"),
        (
            instrument(
                market="hk_stock",
                instrument_type="index",
                provider_symbol="HSI.HK",
            ),
            "none",
        ),
    ],
    ids=["raw-stock", "raw-etf", "adjusted-index", "wrong-market", "unknown-hk-index"],
)
def test_unsupported_combinations_fail_before_sdk(
    monkeypatch: pytest.MonkeyPatch,
    candidate: InstrumentDTO,
    adjustment: str,
) -> None:
    constructor, _ = patch_history(monkeypatch, pd.DataFrame())

    with pytest.raises(ProviderCompatibilityError):
        adapter.YahooOhlcvProvider().fetch_daily(
            candidate,
            date(2026, 1, 2),
            date(2026, 1, 3),
            adjustment,  # type: ignore[arg-type]
        )
    constructor.assert_not_called()


@pytest.mark.parametrize("symbol", ["", "0700.HK;rm", "ABC DEF", None])
def test_invalid_provider_symbols_fail_before_sdk(
    monkeypatch: pytest.MonkeyPatch, symbol: object
) -> None:
    constructor, _ = patch_history(monkeypatch, pd.DataFrame())

    with pytest.raises(ProviderDataInvalid):
        adapter.YahooOhlcvProvider().fetch_daily(
            instrument(provider_symbol=symbol),
            date(2026, 1, 2),
            date(2026, 1, 3),
            "qfq",
        )
    constructor.assert_not_called()
