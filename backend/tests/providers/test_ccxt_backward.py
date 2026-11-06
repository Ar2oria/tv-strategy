"""Provider-correct backward CCXT discovery and boundary regressions."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import ccxt
import pytest

import app.providers.ccxt_ohlcv as adapter
from app.config.models import CryptoSymbol
from app.domain.dto import InstrumentDTO
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import ProviderDataInvalid, ProviderRateLimited

UTC = timezone.utc
NOW = datetime(2026, 1, 11, 12, tzinfo=UTC)
DAY_MS = 86_400_000
EPOCH = date(1970, 1, 1)


def milliseconds(day: date) -> int:
    return (day - EPOCH).days * DAY_MS


def end_milliseconds(day: date) -> int:
    return milliseconds(day) + DAY_MS - 1


def candle(day: date) -> list[object]:
    return [milliseconds(day), 10.0, 12.0, 9.0, 11.0, 100.0]


def instrument(exchange: str) -> InstrumentDTO:
    return crypto_instrument(CryptoSymbol(exchange=exchange, symbol="BTC/USDT"))  # type: ignore[arg-type]


def install(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
    pages: object,
) -> tuple[Mock, Mock]:
    exchange = Mock(name=exchange_id)
    exchange.fetch_ohlcv.side_effect = pages
    constructor = Mock(return_value=exchange)
    monkeypatch.setattr(adapter.ccxt, exchange_id, constructor)
    return exchange, constructor


def fetch(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
    pages: object,
    *,
    start: date | None,
    end: date,
    timeout: float = 20.0,
) -> tuple[list[object], Mock, Mock]:
    exchange, constructor = install(monkeypatch, exchange_id, pages)
    provider = adapter.CcxtOhlcvProvider(
        exchange_id,  # type: ignore[arg-type]
        clock=lambda: NOW,
        request_timeout_seconds=timeout,
    )
    rows = provider.fetch_daily(instrument(exchange_id), start, end, "none")
    return rows, exchange, constructor


@pytest.mark.parametrize(
    ("exchange_id", "limit"),
    [("binance", 1000), ("okx", 100)],
)
def test_short_pages_continue_backward_until_requested_start(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
    limit: int,
) -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 10)
    pages = [
        [candle(date(2026, 1, 8)), candle(end)],
        [candle(date(2026, 1, 3)), candle(date(2026, 1, 7))],
        [candle(start), candle(date(2026, 1, 2))],
    ]

    rows, exchange, _ = fetch(
        monkeypatch, exchange_id, pages, start=start, end=end
    )

    assert [row.time for row in rows] == [  # type: ignore[attr-defined]
        start,
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 7),
        date(2026, 1, 8),
        end,
    ]
    assert exchange.fetch_ohlcv.call_count == 3
    for call in exchange.fetch_ohlcv.call_args_list:
        assert call.kwargs["since"] == milliseconds(start)
        assert call.kwargs["limit"] == limit
        if exchange_id == "okx":
            assert call.kwargs["params"]["type"] == "HistoryCandles"
        else:
            assert "type" not in call.kwargs["params"]
    assert exchange.fetch_ohlcv.call_args_list[0].kwargs["params"]["until"] == end_milliseconds(end)
    assert exchange.fetch_ohlcv.call_args_list[1].kwargs["params"]["until"] == milliseconds(date(2026, 1, 8)) - 1
    assert exchange.fetch_ohlcv.call_args_list[2].kwargs["params"]["until"] == milliseconds(date(2026, 1, 3)) - 1
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("exchange_id", "limit"),
    [("binance", 1000), ("okx", 100)],
)
def test_empty_prelisting_windows_do_not_discard_later_history(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
    limit: int,
) -> None:
    start = date(2020, 1, 1)
    end = date(2026, 1, 10)
    listed = end - timedelta(days=limit + 5)
    request_count = 0

    def pages(*args: object, **kwargs: object) -> list[list[object]]:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return []
        if request_count == 2:
            return [candle(listed)]
        return []

    rows, exchange, _ = fetch(
        monkeypatch, exchange_id, pages, start=start, end=end
    )

    assert [row.time for row in rows] == [listed]  # type: ignore[attr-defined]
    assert exchange.fetch_ohlcv.call_count > 3
    assert any(
        call.kwargs["since"] == milliseconds(start)
        and call.kwargs["params"]["until"] == milliseconds(start) + limit * DAY_MS - 1
        for call in exchange.fetch_ohlcv.call_args_list
    )
    exchange.close.assert_called_once_with()


def test_binance_forward_shaped_full_first_page_discovers_later_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = date(2020, 1, 1)
    first_page = [candle(start + timedelta(days=offset)) for offset in range(1000)]
    later_start = start + timedelta(days=1000)
    end = start + timedelta(days=1004)
    later_page = [candle(later_start + timedelta(days=offset)) for offset in range(5)]

    rows, exchange, _ = fetch(
        monkeypatch, "binance", [first_page, later_page, []], start=start, end=end
    )

    assert len(rows) == 1005
    assert rows[0].time == start  # type: ignore[attr-defined]
    assert rows[-1].time == end  # type: ignore[attr-defined]
    assert exchange.fetch_ohlcv.call_count == 3
    assert exchange.fetch_ohlcv.call_args_list[0].kwargs["since"] == milliseconds(start)
    assert exchange.fetch_ohlcv.call_args_list[1].kwargs["since"] == (
        milliseconds(start + timedelta(days=999)) + 1
    )


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_null_start_discovers_back_to_epoch_instead_of_stopping_at_short_page(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    pages = [
        [candle(date(1970, 1, 2)), candle(date(1970, 1, 3))],
        [],
        [],
    ]

    rows, exchange, _ = fetch(
        monkeypatch,
        exchange_id,
        pages,
        start=None,
        end=date(1970, 1, 3),
    )

    assert [row.time for row in rows] == [date(1970, 1, 2), date(1970, 1, 3)]  # type: ignore[attr-defined]
    assert exchange.fetch_ohlcv.call_count == 2
    assert all(call.kwargs["since"] == 0 for call in exchange.fetch_ohlcv.call_args_list)
    assert exchange.fetch_ohlcv.call_args_list[-1].kwargs["params"]["until"] == (
        milliseconds(date(1970, 1, 2)) - 1
    )


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_exact_start_end_boundary_is_inclusive_and_stops(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    boundary = date(2026, 1, 2)

    rows, exchange, _ = fetch(
        monkeypatch,
        exchange_id,
        [[candle(boundary)]],
        start=boundary,
        end=boundary,
    )

    assert [row.time for row in rows] == [boundary]  # type: ignore[attr-defined]
    exchange.fetch_ohlcv.assert_called_once()
    assert exchange.fetch_ohlcv.call_args.kwargs["params"]["until"] == end_milliseconds(boundary)


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_empty_exact_start_window_terminates_without_underflow(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    boundary = date(2026, 1, 2)

    rows, exchange, _ = fetch(
        monkeypatch, exchange_id, [[], []], start=boundary, end=boundary
    )

    assert rows == []
    assert exchange.fetch_ohlcv.call_count == 1
    assert exchange.fetch_ohlcv.call_args.kwargs["params"]["until"] == end_milliseconds(boundary)


@pytest.mark.parametrize(
    "bad_day",
    [date(2025, 12, 31), date(2026, 1, 4), date(2026, 1, 5)],
)
def test_rows_outside_requested_or_completed_window_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    bad_day: date,
) -> None:
    rows = [candle(date(2026, 1, 2)), candle(bad_day)]
    with pytest.raises(ProviderDataInvalid, match="window|range"):
        fetch(
            monkeypatch,
            "binance",
            [rows],
            start=date(2026, 1, 2),
            end=date(2026, 1, 3),
        )


def test_falsey_injected_clock_is_still_used(monkeypatch: pytest.MonkeyPatch) -> None:
    class FalseyClock:
        def __init__(self) -> None:
            self.calls = 0

        def __bool__(self) -> bool:
            return False

        def __call__(self) -> datetime:
            self.calls += 1
            return NOW

    clock = FalseyClock()
    exchange, _ = install(monkeypatch, "binance", [[candle(date(2026, 1, 2))]])

    rows = adapter.CcxtOhlcvProvider("binance", clock=clock).fetch_daily(
        instrument("binance"), date(2026, 1, 2), date(2026, 1, 2), "none"
    )

    assert len(rows) == 1
    assert clock.calls == 1


def test_ccxt_receives_native_timeout_in_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = date(2026, 1, 2)

    _, _, constructor = fetch(
        monkeypatch,
        "binance",
        [[candle(boundary)]],
        start=boundary,
        end=boundary,
        timeout=1.25,
    )

    constructor.assert_called_once_with({"enableRateLimit": True, "timeout": 1250})


@pytest.mark.parametrize("guidance", ["65", "invalid", "nan", "-2"])
def test_ccxt_rate_limit_uses_only_valid_structured_retry_after(
    monkeypatch: pytest.MonkeyPatch,
    guidance: str,
) -> None:
    error = ccxt.RateLimitExceeded("private upstream body")
    error.response = SimpleNamespace(headers={"Retry-After": guidance})
    exchange, _ = install(monkeypatch, "binance", [error])
    provider = adapter.CcxtOhlcvProvider("binance", clock=lambda: NOW)

    with pytest.raises(ProviderRateLimited) as captured:
        provider.fetch_daily(
            instrument("binance"), date(2026, 1, 2), date(2026, 1, 2), "none"
        )

    assert captured.value.retry_after == (65.0 if guidance == "65" else None)
    assert "private upstream body" not in str(captured.value)
    exchange.close.assert_called_once_with()
