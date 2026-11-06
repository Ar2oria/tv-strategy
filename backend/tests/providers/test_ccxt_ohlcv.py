"""Offline CCXT spot OHLCV pagination and normalization tests."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, call

import ccxt
import pytest

import app.providers.ccxt_ohlcv as adapter
from app.config.models import CryptoSymbol
from app.domain.dto import BarDTO, InstrumentDTO
from app.providers.base import OhlcvProvider
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderConfigurationError,
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
)

UTC = timezone.utc
NOW = datetime(2026, 1, 5, 23, 30, tzinfo=UTC)
DAY_MS = 86_400_000
BTC = crypto_instrument(CryptoSymbol(exchange="binance", symbol="BTC/USDT"))


def at(day: date, hour: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def milliseconds(value: date | datetime) -> int:
    moment = at(value) if isinstance(value, date) and not isinstance(value, datetime) else value
    assert isinstance(moment, datetime)
    return int(moment.timestamp() * 1000)


def candle(
    value: date | datetime = date(2026, 1, 2),
    *,
    open: object = 10.0,
    high: object = 12.0,
    low: object = 9.0,
    close: object = 11.0,
    volume: object = 100.0,
    timestamp: object | None = None,
) -> list[object]:
    return [
        milliseconds(value) if timestamp is None else timestamp,
        open,
        high,
        low,
        close,
        volume,
    ]


def candles(start: date, count: int) -> list[list[object]]:
    return [candle(start + timedelta(days=offset)) for offset in range(count)]


def expected(day: date, exchange: str = "binance") -> BarDTO:
    return BarDTO(
        time=day,
        open=10.0,
        high=12.0,
        low=9.0,
        close=11.0,
        volume=100.0,
        source=exchange,
        adjustment="none",
    )


def install_exchange(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
    pages: object,
) -> tuple[Mock, Mock]:
    exchange = Mock(name=f"{exchange_id}-exchange")
    exchange.fetch_ohlcv.side_effect = pages
    constructor = Mock(name=f"{exchange_id}-constructor", return_value=exchange)
    monkeypatch.setattr(adapter.ccxt, exchange_id, constructor)
    return exchange, constructor


def fetch(
    exchange_id: str = "binance",
    instrument: InstrumentDTO = BTC,
    start: date | None = date(2026, 1, 2),
    end: date = date(2026, 1, 3),
    clock: object = lambda: NOW,
) -> list[BarDTO]:
    return adapter.CcxtOhlcvProvider(
        exchange_id, clock=clock  # type: ignore[arg-type]
    ).fetch_daily(instrument, start, end, "none")


def test_binance_uses_bounded_daily_limit_and_inclusive_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange, constructor = install_exchange(
        monkeypatch,
        "binance",
        [[
            candle(date(2026, 1, 2), open="10", high="12", low="9", close="11", volume="100"),
            candle(date(2026, 1, 3)),
        ]],
    )

    result = fetch()

    constructor.assert_called_once_with({"enableRateLimit": True, "timeout": 20_000})
    exchange.fetch_ohlcv.assert_called_once_with(
        "BTC/USDT",
        timeframe="1d",
        since=milliseconds(date(2026, 1, 2)),
        limit=1000,
        params={"until": milliseconds(date(2026, 1, 4)) - 1},
    )
    assert result == [expected(date(2026, 1, 2)), expected(date(2026, 1, 3))]
    exchange.close.assert_called_once_with()
    exchange.fetch_paginated_call_deterministic.assert_not_called()
    assert isinstance(adapter.CcxtOhlcvProvider("binance"), OhlcvProvider)


def test_binance_full_page_moves_backward_and_short_page_reaches_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = date(2023, 1, 1)
    second_day = start + timedelta(days=1)
    first_page = candles(second_day, 1000)
    final_day = start + timedelta(days=1000)
    exchange, _ = install_exchange(
        monkeypatch, "binance", [first_page, [candle(start)]]
    )

    result = fetch(start=start, end=final_day)

    assert len(result) == 1001
    assert result[0].time == start
    assert result[-1].time == final_day
    assert exchange.fetch_ohlcv.call_args_list == [
        call(
            "BTC/USDT",
            timeframe="1d",
            since=milliseconds(start),
            limit=1000,
            params={"until": milliseconds(final_day + timedelta(days=1)) - 1},
        ),
        call(
            "BTC/USDT",
            timeframe="1d",
            since=milliseconds(start),
            limit=1000,
            params={"until": milliseconds(second_day) - 1},
        ),
    ]
    exchange.close.assert_called_once_with()


def test_none_start_begins_at_unix_epoch_and_empty_windows_are_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange, _ = install_exchange(
        monkeypatch, "binance", lambda *args, **kwargs: []
    )

    assert fetch(start=None) == []
    assert exchange.fetch_ohlcv.call_args_list[0].kwargs["since"] == 0
    assert any(
        call.kwargs["since"] == 0
        and call.kwargs["params"]["until"] == 1000 * DAY_MS - 1
        for call in exchange.fetch_ohlcv.call_args_list
    )
    exchange.close.assert_called_once_with()


def test_okx_uses_history_candles_limit_100_and_backward_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = date(2025, 1, 1)
    second_day = start + timedelta(days=1)
    first_page = candles(second_day, 100)
    final_day = start + timedelta(days=100)
    okx_instrument = crypto_instrument(
        CryptoSymbol(exchange="okx", symbol="BTC/USDT")
    )
    exchange, constructor = install_exchange(
        monkeypatch, "okx", [first_page, [candle(start)]]
    )

    result = fetch(
        "okx", okx_instrument, start=start, end=final_day
    )

    constructor.assert_called_once_with({"enableRateLimit": True, "timeout": 20_000})
    assert exchange.fetch_ohlcv.call_args_list == [
        call(
            "BTC/USDT",
            timeframe="1d",
            since=milliseconds(start),
            limit=100,
            params={
                "type": "HistoryCandles",
                "until": milliseconds(final_day + timedelta(days=1)) - 1,
            },
        ),
        call(
            "BTC/USDT",
            timeframe="1d",
            since=milliseconds(start),
            limit=100,
            params={"type": "HistoryCandles", "until": milliseconds(second_day) - 1},
        ),
    ]
    assert len(result) == 101
    assert all(row.source == "okx" for row in result)
    assert result[-1] == expected(final_day, "okx")
    exchange.close.assert_called_once_with()


def test_full_page_reaching_inclusive_end_does_not_need_an_empty_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = date(2025, 1, 1)
    page = candles(start, 100)
    end = start + timedelta(days=99)
    okx_instrument = crypto_instrument(CryptoSymbol(exchange="okx", symbol="BTC/USDT"))
    exchange, _ = install_exchange(monkeypatch, "okx", [page])

    result = fetch("okx", okx_instrument, start=start, end=end)

    assert len(result) == 100
    assert result[-1].time == end
    assert exchange.fetch_ohlcv.call_count == 1


def test_frozen_utc_clock_rejects_today_and_future_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange, _ = install_exchange(
        monkeypatch,
        "binance",
        [[
            candle(date(2026, 1, 3)),
            candle(datetime(2026, 1, 4, 23, 59, tzinfo=UTC)),
            candle(date(2026, 1, 5)),
            candle(date(2026, 1, 6)),
        ]],
    )
    clock = Mock(return_value=NOW)

    with pytest.raises(ProviderDataInvalid, match="outside"):
        fetch(start=date(2026, 1, 3), end=date(2026, 1, 10), clock=clock)

    clock.assert_called_once_with()
    exchange.close.assert_called_once_with()


def test_completed_utc_day_intraday_timestamp_remains_in_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange, _ = install_exchange(
        monkeypatch,
        "binance",
        [[
            candle(date(2026, 1, 3)),
            candle(datetime(2026, 1, 4, 23, 59, tzinfo=UTC)),
        ]],
    )

    result = fetch(start=date(2026, 1, 3), end=date(2026, 1, 10))

    assert [row.time for row in result] == [date(2026, 1, 3), date(2026, 1, 4)]
    exchange.close.assert_called_once_with()


def test_clock_is_converted_to_utc_before_rejecting_unfinished_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange, _ = install_exchange(
        monkeypatch,
        "binance",
        [[candle(date(2026, 1, 3)), candle(date(2026, 1, 4))]],
    )
    clock = lambda: datetime(2026, 1, 5, 0, 15, tzinfo=timezone(timedelta(hours=2)))

    with pytest.raises(ProviderDataInvalid, match="outside"):
        fetch(start=date(2026, 1, 3), end=date(2026, 1, 5), clock=clock)

    exchange.close.assert_called_once_with()


def test_repeated_full_page_fails_visibly_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_start = date(2024, 1, 1)
    page = candles(date(2025, 1, 1), 100)
    okx_instrument = crypto_instrument(CryptoSymbol(exchange="okx", symbol="BTC/USDT"))
    exchange, _ = install_exchange(monkeypatch, "okx", [page, page])

    with pytest.raises(ProviderDataInvalid, match="[Rr]epeated|[Dd]uplicate"):
        fetch("okx", okx_instrument, start=requested_start, end=date(2025, 12, 31))
    assert exchange.fetch_ohlcv.call_count == 2
    exchange.close.assert_called_once_with()


def test_non_advancing_page_fails_instead_of_looping_or_returning_partial_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_start = date(2024, 1, 1)
    pages = [candles(date(2025, 1, 1), 100), candles(date(2024, 6, 1), 100)]
    okx_instrument = crypto_instrument(CryptoSymbol(exchange="okx", symbol="BTC/USDT"))
    exchange, _ = install_exchange(monkeypatch, "okx", pages)

    with pytest.raises(ProviderDataInvalid, match="[Nn]on-advancing"):
        fetch("okx", okx_instrument, start=requested_start, end=date(2025, 12, 31))
    assert exchange.fetch_ohlcv.call_count == 2
    exchange.close.assert_called_once_with()


def test_hard_page_cap_never_returns_partial_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "MAX_PAGES", 1)
    requested_start = date(2020, 1, 1)
    pages = [candles(date(2025, 1, 1), 100)]
    okx_instrument = crypto_instrument(CryptoSymbol(exchange="okx", symbol="BTC/USDT"))
    exchange, _ = install_exchange(monkeypatch, "okx", pages)

    with pytest.raises(ProviderUnavailable) as captured:
        fetch("okx", okx_instrument, start=requested_start, end=date(2026, 1, 4))
    assert "page limit" in (captured.value.detail or "")
    assert "page limit" not in str(captured.value)
    assert exchange.fetch_ohlcv.call_count == 1
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize(
    "second_page",
    [
        [candle(date(2026, 1, 2)), candle(date(2026, 1, 2))],
        [
            candle(date(2026, 1, 2)),
            candle(datetime(2026, 1, 2, 12, tzinfo=UTC)),
        ],
    ],
    ids=["same-timestamp", "same-utc-date"],
)
def test_duplicate_dates_within_a_page_reject_complete_response(
    monkeypatch: pytest.MonkeyPatch, second_page: list[list[object]]
) -> None:
    exchange, _ = install_exchange(monkeypatch, "binance", [second_page])

    with pytest.raises(ProviderDataInvalid, match="Duplicate"):
        fetch()
    exchange.close.assert_called_once_with()


def test_duplicate_across_pages_is_not_silently_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_start = date(2024, 1, 1)
    first_page = candles(date(2025, 1, 1), 100)
    overlap = first_page[-1]
    older = candle(date(2024, 12, 31))
    okx_instrument = crypto_instrument(CryptoSymbol(exchange="okx", symbol="BTC/USDT"))
    exchange, _ = install_exchange(monkeypatch, "okx", [first_page, [overlap, older]])

    with pytest.raises(ProviderDataInvalid, match="Duplicate"):
        fetch("okx", okx_instrument, start=requested_start, end=date(2025, 12, 31))
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf"), None])
def test_non_finite_or_missing_ohlcv_values_fail_visibly(
    monkeypatch: pytest.MonkeyPatch, field: str, bad_value: object
) -> None:
    row = candle(**{field: bad_value})
    exchange, _ = install_exchange(monkeypatch, "binance", [[row]])

    with pytest.raises(ProviderDataInvalid, match="finite"):
        fetch()
    exchange.close.assert_called_once_with()


def test_invalid_unfinished_or_out_of_range_row_is_validated_before_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [candle(), candle(date(2026, 1, 5), open=float("nan"))]
    exchange, _ = install_exchange(monkeypatch, "binance", [rows])

    with pytest.raises(ProviderDataInvalid, match="finite"):
        fetch(end=date(2026, 1, 10))
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize(
    "row",
    [
        None,
        {},
        "not-a-row",
        [],
        [milliseconds(date(2026, 1, 2))] * 5,
        candle() + [123],
        candle(timestamp="not-a-timestamp"),
        candle(timestamp=True),
        candle(timestamp=1.5),
        candle(timestamp=float("nan")),
        candle(timestamp=10**30),
        candle(open=13),
        candle(close=13),
        candle(low=13),
        candle(volume=-1),
    ],
    ids=[
        "null",
        "mapping",
        "string",
        "empty",
        "short",
        "long",
        "bad-timestamp",
        "boolean-timestamp",
        "fractional-timestamp",
        "nan-timestamp",
        "overflow-timestamp",
        "open-above-high",
        "close-above-high",
        "low-above-high",
        "negative-volume",
    ],
)
def test_malformed_rows_fail_visibly_and_close(
    monkeypatch: pytest.MonkeyPatch, row: object
) -> None:
    exchange, _ = install_exchange(monkeypatch, "binance", [[row]])

    with pytest.raises(ProviderDataInvalid):
        fetch()
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize("page", [None, {}, "not-a-page", 42, iter([])])
def test_malformed_page_is_not_treated_as_empty(
    monkeypatch: pytest.MonkeyPatch, page: object
) -> None:
    exchange, _ = install_exchange(monkeypatch, "binance", [page])

    with pytest.raises(ProviderDataInvalid):
        fetch()
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize(
    "upstream_error",
    [
        ccxt.RateLimitExceeded("HTTP 429 secret-rate-limit"),
        ccxt.DDoSProtection("HTTP 418 secret-ban"),
        ccxt.ExchangeError("HTTP status 429 secret-status"),
        ccxt.ExchangeError("HTTP/1.1 418 secret-status"),
        ccxt.ExchangeError("status=429 secret-status"),
        ccxt.ExchangeError("status:418 secret-status"),
        ccxt.ExchangeError("status_code=429 secret-status"),
    ],
    ids=[
        "rate-limit-class",
        "ddos-class",
        "http-status-429",
        "http-418",
        "status-equals-429",
        "status-colon-418",
        "status-code-equals-429",
    ],
)
def test_429_and_418_are_sanitized_rate_limit_errors_and_close(
    monkeypatch: pytest.MonkeyPatch, upstream_error: Exception
) -> None:
    exchange, _ = install_exchange(monkeypatch, "binance", [upstream_error])

    with pytest.raises(ProviderRateLimited) as captured:
        fetch()
    assert "secret" not in str(captured.value)
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize(
    "upstream_error",
    [
        ccxt.ExchangeError("secret-exchange-detail"),
        ccxt.ExchangeError("status=403 secret-status"),
        ccxt.NetworkError("secret-network-detail"),
        ccxt.RequestTimeout("secret-timeout-detail"),
        RuntimeError("secret-unexpected-detail"),
    ],
)
def test_exchange_failures_are_typed_sanitized_and_close(
    monkeypatch: pytest.MonkeyPatch, upstream_error: Exception
) -> None:
    exchange, _ = install_exchange(monkeypatch, "binance", [upstream_error])

    with pytest.raises(ProviderUnavailable) as captured:
        fetch()
    assert "secret" not in str(captured.value)
    exchange.close.assert_called_once_with()


def test_constructor_failure_is_typed_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor = Mock(side_effect=ccxt.ExchangeError("secret-constructor-detail"))
    monkeypatch.setattr(adapter.ccxt, "binance", constructor)

    with pytest.raises(ProviderUnavailable) as captured:
        fetch()
    assert "secret" not in str(captured.value)


def test_close_failure_is_typed_on_success_but_does_not_mask_data_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange, _ = install_exchange(monkeypatch, "binance", [[], []])
    exchange.close.side_effect = RuntimeError("secret-close-detail")
    with pytest.raises(ProviderUnavailable) as close_error:
        fetch()
    assert "secret" not in str(close_error.value)

    exchange.fetch_ohlcv.side_effect = [[candle(open=float("nan"))]]
    with pytest.raises(ProviderDataInvalid):
        fetch()
    assert exchange.close.call_count == 2


def test_each_fetch_owns_and_closes_a_fresh_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = Mock(name="first")
    second = Mock(name="second")
    first.fetch_ohlcv.return_value = []
    second.fetch_ohlcv.return_value = []
    constructor = Mock(side_effect=[first, second])
    monkeypatch.setattr(adapter.ccxt, "binance", constructor)
    provider = adapter.CcxtOhlcvProvider("binance", clock=lambda: NOW)

    assert provider.fetch_daily(BTC, None, date(2026, 1, 3), "none") == []
    assert provider.fetch_daily(BTC, None, date(2026, 1, 3), "none") == []
    assert constructor.call_count == 2
    first.close.assert_called_once_with()
    second.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("candidate", "adjustment", "error_type"),
    [
        (BTC, "qfq", ProviderCompatibilityError),
        (replace(BTC, market="us_stock"), "none", ProviderCompatibilityError),
        (replace(BTC, instrument_type="stock"), "none", ProviderCompatibilityError),
        (replace(BTC, exchange="okx"), "none", ProviderCompatibilityError),
        (replace(BTC, exchange="BINANCE"), "none", ProviderCompatibilityError),
        (replace(BTC, symbol="BTC/USDT"), "none", ProviderDataInvalid),
        (replace(BTC, symbol="OKX:BTC/USDT"), "none", ProviderDataInvalid),
    ],
)
def test_incompatible_instruments_fail_before_sdk(
    monkeypatch: pytest.MonkeyPatch,
    candidate: InstrumentDTO,
    adjustment: str,
    error_type: type[Exception],
) -> None:
    constructor = Mock()
    monkeypatch.setattr(adapter.ccxt, "binance", constructor)

    with pytest.raises(error_type):
        adapter.CcxtOhlcvProvider("binance", clock=lambda: NOW).fetch_daily(
            candidate,
            date(2026, 1, 2),
            date(2026, 1, 3),
            adjustment,  # type: ignore[arg-type]
        )
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "pair",
    [
        "BTC/USDT:USDT",
        "BTC-PERP",
        "BTC/USDT/USD",
        "btc/USDT",
        " BTC/USDT",
        "BTC-USDT",
        "",
        None,
    ],
)
def test_malformed_or_derivative_provider_symbols_fail_before_sdk(
    monkeypatch: pytest.MonkeyPatch, pair: object
) -> None:
    constructor = Mock()
    monkeypatch.setattr(adapter.ccxt, "binance", constructor)

    with pytest.raises(ProviderDataInvalid):
        fetch(instrument=replace(BTC, provider_symbol=pair))  # type: ignore[arg-type]
    constructor.assert_not_called()


@pytest.mark.parametrize(
    ("start", "end"),
    [(date(2026, 1, 4), date(2026, 1, 3)), ("2026-01-02", date(2026, 1, 3))],
)
def test_invalid_fetch_range_fails_before_sdk(
    monkeypatch: pytest.MonkeyPatch, start: object, end: date
) -> None:
    constructor = Mock()
    monkeypatch.setattr(adapter.ccxt, "binance", constructor)

    with pytest.raises(ProviderDataInvalid):
        fetch(start=start, end=end)  # type: ignore[arg-type]
    constructor.assert_not_called()


@pytest.mark.parametrize("clock", [lambda: datetime(2026, 1, 5), lambda: "today"])
def test_invalid_clock_result_fails_before_sdk(
    monkeypatch: pytest.MonkeyPatch, clock: object
) -> None:
    constructor = Mock()
    monkeypatch.setattr(adapter.ccxt, "binance", constructor)

    with pytest.raises(ProviderDataInvalid, match="clock"):
        fetch(clock=clock)
    constructor.assert_not_called()


def test_range_with_no_completed_utc_day_returns_empty_without_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor = Mock()
    monkeypatch.setattr(adapter.ccxt, "binance", constructor)

    assert fetch(start=date(2026, 1, 5), end=date(2026, 1, 8)) == []
    constructor.assert_not_called()


def test_unsupported_exchange_id_fails_during_construction() -> None:
    with pytest.raises(ProviderConfigurationError):
        adapter.CcxtOhlcvProvider("coinbase")  # type: ignore[arg-type]
