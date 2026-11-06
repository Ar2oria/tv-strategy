"""Yahoo timeout, rate-limit, index-volume, and range contracts."""

from dataclasses import replace
from datetime import date
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError
from yfinance.scrapers.history import PriceHistory

import app.providers.yahoo_ohlcv as adapter
from app.domain.dto import InstrumentDTO
from app.providers.errors import (
    ProviderDataInvalid,
    ProviderRateLimited,
)

US_STOCK = InstrumentDTO(
    symbol="AAPL",
    name="Apple",
    market="us_stock",
    exchange="NASDAQ",
    currency="USD",
    timezone="America/New_York",
    instrument_type="stock",
    provider_symbol="AAPL",
)
NDX = replace(
    US_STOCK,
    symbol="^NDX",
    name="Nasdaq-100",
    instrument_type="index",
    provider_symbol="^NDX",
)
HSTECH = replace(
    NDX,
    symbol="HSTECH.HK",
    name="Hang Seng TECH",
    market="hk_stock",
    exchange="HKEX",
    currency="HKD",
    timezone="Asia/Hong_Kong",
    provider_symbol="HSTECH.HK",
)
MISSING = object()


def frame(volumes: object = [1000.0]) -> pd.DataFrame:
    values = {
        "Open": [10.0],
        "High": [12.0],
        "Low": [9.0],
        "Close": [11.0],
    }
    if volumes is not MISSING:
        values["Volume"] = volumes  # type: ignore[assignment]
    return pd.DataFrame(values, index=pd.Index([pd.Timestamp("2026-01-02")]))


def patch_history(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
) -> Mock:
    history = Mock()
    if isinstance(response, Exception):
        history.side_effect = response
    else:
        history.return_value = response
    ticker = Mock()
    ticker.history = history
    monkeypatch.setattr(adapter.yf, "Ticker", Mock(return_value=ticker))
    return history


@pytest.mark.parametrize("candidate", [NDX, HSTECH], ids=["^NDX", "HSTECH.HK"])
@pytest.mark.parametrize(
    "volume",
    [None, float("nan"), pd.NA, 0, 0.0, MISSING],
    ids=["none", "nan", "pd-na", "zero-int", "zero-float", "missing-column"],
)
def test_index_missing_nan_and_zero_volume_are_unavailable_not_invalid(
    monkeypatch: pytest.MonkeyPatch,
    candidate: InstrumentDTO,
    volume: object,
) -> None:
    patch_history(monkeypatch, frame(MISSING if volume is MISSING else [volume]))

    rows = adapter.YahooOhlcvProvider().fetch_daily(
        candidate, date(2026, 1, 2), date(2026, 1, 2), "none"
    )

    assert len(rows) == 1
    assert rows[0].volume is None
    assert rows[0].source == "yfinance"
    assert rows[0].adjustment == "none"


def test_positive_index_volume_is_preserved_and_stock_zero_remains_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_history(monkeypatch, frame([1234.0]))
    index_rows = adapter.YahooOhlcvProvider().fetch_daily(
        NDX, date(2026, 1, 2), date(2026, 1, 2), "none"
    )
    assert index_rows[0].volume == 1234.0

    patch_history(monkeypatch, frame([0.0]))
    stock_rows = adapter.YahooOhlcvProvider().fetch_daily(
        US_STOCK, date(2026, 1, 2), date(2026, 1, 2), "qfq"
    )
    assert stock_rows[0].volume == 0.0


@pytest.mark.parametrize("volume", [None, float("nan"), MISSING])
def test_stock_and_etf_volume_stays_strict(
    monkeypatch: pytest.MonkeyPatch,
    volume: object,
) -> None:
    patch_history(monkeypatch, frame(MISSING if volume is MISSING else [volume]))

    with pytest.raises(ProviderDataInvalid):
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 2), "qfq"
        )


def test_native_history_timeout_uses_snapshot_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = patch_history(monkeypatch, frame())

    adapter.YahooOhlcvProvider(request_timeout_seconds=3.75).fetch_daily(
        US_STOCK, date(2026, 1, 2), date(2026, 1, 2), "qfq"
    )

    assert history.call_args.kwargs["timeout"] == 3.75


def test_history_kwargs_match_the_installed_native_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = patch_history(monkeypatch, frame())

    adapter.YahooOhlcvProvider().fetch_daily(
        US_STOCK, date(2026, 1, 2), date(2026, 1, 2), "qfq"
    )

    supported = set(inspect.signature(PriceHistory.history).parameters)
    assert set(history.call_args.kwargs) <= supported
    assert "threads" not in history.call_args.kwargs
    assert "progress" not in history.call_args.kwargs


@pytest.mark.parametrize("guidance", ["75", "invalid", "nan", "-1"])
def test_yahoo_rate_limit_is_typed_and_copies_only_real_guidance(
    monkeypatch: pytest.MonkeyPatch,
    guidance: str,
) -> None:
    error = YFRateLimitError()
    error.response = SimpleNamespace(headers={"Retry-After": guidance})
    patch_history(monkeypatch, error)

    with pytest.raises(ProviderRateLimited) as captured:
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 2), "qfq"
        )

    assert captured.value.retry_after == (75.0 if guidance == "75" else None)
    assert "Rate limited" not in str(captured.value)


@pytest.mark.parametrize("bad_day", [date(2026, 1, 1), date(2026, 1, 3)])
def test_out_of_range_yahoo_rows_are_rejected_not_silently_filtered(
    monkeypatch: pytest.MonkeyPatch,
    bad_day: date,
) -> None:
    malicious = pd.DataFrame(
        {
            "Open": [10.0, 10.0],
            "High": [12.0, 12.0],
            "Low": [9.0, 9.0],
            "Close": [11.0, 11.0],
            "Volume": [100.0, 100.0],
        },
        index=pd.Index([pd.Timestamp("2026-01-02"), pd.Timestamp(bad_day)]),
    )
    patch_history(monkeypatch, malicious)

    with pytest.raises(ProviderDataInvalid, match="range"):
        adapter.YahooOhlcvProvider().fetch_daily(
            US_STOCK, date(2026, 1, 2), date(2026, 1, 2), "qfq"
        )
