"""Complete forward-shaped CCXT history discovery regressions."""

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import app.providers.ccxt_ohlcv as adapter
from app.config.models import CryptoSymbol
from app.domain.dto import BarDTO, InstrumentDTO
from app.providers.crypto_catalog import crypto_instrument
from app.providers.errors import ProviderDataInvalid, ProviderUnavailable

UTC = timezone.utc
NOW = datetime(2027, 1, 1, tzinfo=UTC)
EPOCH = date(1970, 1, 1)
DAY_MS = 86_400_000


def milliseconds(day: date) -> int:
    return (day - EPOCH).days * DAY_MS


def candle(day: date) -> list[object]:
    return [milliseconds(day), 10.0, 12.0, 9.0, 11.0, 100.0]


def dates(start: date, count: int) -> tuple[date, ...]:
    return tuple(start + timedelta(days=offset) for offset in range(count))


def instrument(exchange_id: str) -> InstrumentDTO:
    return crypto_instrument(
        CryptoSymbol(exchange=exchange_id, symbol="BTC/USDT")  # type: ignore[arg-type]
    )


def fetch_with(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
    responder: Callable[..., object],
    *,
    start: date | None,
    end: date,
) -> tuple[list[BarDTO], Mock]:
    exchange = Mock(name=exchange_id)
    exchange.fetch_ohlcv.side_effect = responder
    monkeypatch.setattr(adapter.ccxt, exchange_id, Mock(return_value=exchange))
    rows = adapter.CcxtOhlcvProvider(
        exchange_id,  # type: ignore[arg-type]
        clock=lambda: NOW,
    ).fetch_daily(instrument(exchange_id), start, end, "none")
    return rows, exchange


def forward_responder(
    available: Sequence[date],
    *,
    initial: object = None,
) -> Callable[..., list[list[object]]]:
    calls = 0

    def respond(*args: object, **kwargs: object) -> list[list[object]]:
        nonlocal calls
        calls += 1
        if calls == 1 and initial is not None:
            if isinstance(initial, Exception):
                raise initial
            return initial  # type: ignore[return-value]
        since = kwargs["since"]
        until = kwargs["params"]["until"]  # type: ignore[index]
        limit = kwargs["limit"]
        assert isinstance(since, int)
        assert isinstance(until, int)
        assert isinstance(limit, int)
        return [
            candle(day)
            for day in available
            if since <= milliseconds(day) <= until
        ][:limit]

    return respond


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_full_forward_earliest_page_discovers_every_later_page(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    limit = adapter.PAGE_LIMITS[exchange_id]  # type: ignore[index]
    requested_start = date(2020, 1, 1)
    first_oldest = requested_start + timedelta(days=10)
    available = dates(first_oldest, 2 * limit + 5)
    end = available[-1]

    rows, exchange = fetch_with(
        monkeypatch,
        exchange_id,
        forward_responder(available),
        start=requested_start,
        end=end,
    )

    assert tuple(row.time for row in rows) == available
    first_call = exchange.fetch_ohlcv.call_args_list[0]
    assert first_call.kwargs["since"] == milliseconds(requested_start)
    assert first_call.kwargs["params"]["until"] == milliseconds(end) + DAY_MS - 1
    first_latest = first_oldest + timedelta(days=limit - 1)
    assert any(
        call.kwargs["since"] == milliseconds(first_latest) + 1
        for call in exchange.fetch_ohlcv.call_args_list[1:]
    )
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_exact_start_short_forward_page_does_not_stop_early(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    start = date(2024, 1, 1)
    available = dates(start, 6)
    first_page = [candle(start), candle(available[1])]

    rows, exchange = fetch_with(
        monkeypatch,
        exchange_id,
        forward_responder(available, initial=first_page),
        start=start,
        end=available[-1],
    )

    assert tuple(row.time for row in rows) == available
    assert exchange.fetch_ohlcv.call_count == 3
    assert exchange.fetch_ohlcv.call_args_list[1].kwargs["since"] == (
        milliseconds(available[1]) + 1
    )
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_initial_prelisting_empty_window_still_discovers_later_data(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    limit = adapter.PAGE_LIMITS[exchange_id]  # type: ignore[index]
    start = date(2020, 1, 1)
    listed = start + timedelta(days=2 * limit + 20)
    available = dates(listed, 3)

    rows, exchange = fetch_with(
        monkeypatch,
        exchange_id,
        forward_responder(available, initial=[]),
        start=start,
        end=available[-1],
    )

    assert tuple(row.time for row in rows) == available
    assert exchange.fetch_ohlcv.call_count > 2
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_null_start_and_exact_end_boundary_return_complete_history(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    available = (date(1970, 1, 2), date(1970, 1, 3))

    rows, exchange = fetch_with(
        monkeypatch,
        exchange_id,
        forward_responder(available),
        start=None,
        end=available[-1],
    )

    assert tuple(row.time for row in rows) == available
    assert exchange.fetch_ohlcv.call_args_list[0].kwargs["since"] == 0
    exchange.close.assert_called_once_with()


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_non_advancing_short_response_rejects_instead_of_returning_partial(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    start = date(2024, 1, 1)
    repeated = [candle(start), candle(start + timedelta(days=1))]

    with pytest.raises(
        ProviderDataInvalid, match="non-advancing|outside|Duplicate|repeated"
    ):
        fetch_with(
            monkeypatch,
            exchange_id,
            Mock(return_value=repeated),
            start=start,
            end=start + timedelta(days=5),
        )


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_total_request_cap_rejects_incomplete_forward_discovery(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    monkeypatch.setattr(adapter, "MAX_PAGES", 2)
    start = date(2024, 1, 1)

    def one_row_per_request(*args: object, **kwargs: object) -> list[list[object]]:
        since = kwargs["since"]
        assert isinstance(since, int)
        first = datetime(1970, 1, 1) + timedelta(milliseconds=since)
        day = first.date() + timedelta(days=first.time() != datetime.min.time())
        return [candle(day)]

    with pytest.raises(ProviderUnavailable, match="Market-data provider") as captured:
        fetch_with(
            monkeypatch,
            exchange_id,
            one_row_per_request,
            start=start,
            end=start + timedelta(days=10),
        )
    assert "page limit" in (captured.value.detail or "")


@pytest.mark.parametrize("exchange_id", ["binance", "okx"])
def test_out_of_order_rows_reject_the_complete_response(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    start = date(2024, 1, 1)
    page = [candle(start + timedelta(days=1)), candle(start)]

    with pytest.raises(ProviderDataInvalid, match="ordered|non-advancing"):
        fetch_with(
            monkeypatch,
            exchange_id,
            Mock(return_value=page),
            start=start,
            end=start + timedelta(days=1),
        )
