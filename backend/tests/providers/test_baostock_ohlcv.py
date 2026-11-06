"""Offline session, cursor, and translation tests for BaoStock OHLCV."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from threading import Event, Lock, Thread
from unittest.mock import Mock

import pytest

import app.providers.baostock_ohlcv as adapter
from app.domain.dto import BarDTO, InstrumentDTO
from app.providers.base import OhlcvProvider
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderUnavailable,
)

FIELDS = "date,open,high,low,close,volume,amount"
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


def rows() -> list[list[str]]:
    return [
        ["2026-01-03", "11", "13", "10", "12", "2000", "24000"],
        ["2026-01-02", "9", "12", "8", "11", "1000", "11000"],
    ]


def expected_bars(adjustment: str = "qfq") -> list[BarDTO]:
    return [
        BarDTO(
            time=date(2026, 1, 2),
            open=9.0,
            high=12.0,
            low=8.0,
            close=11.0,
            volume=1000.0,
            source="baostock",
            adjustment=adjustment,  # type: ignore[arg-type]
        ),
        BarDTO(
            time=date(2026, 1, 3),
            open=11.0,
            high=13.0,
            low=10.0,
            close=12.0,
            volume=2000.0,
            source="baostock",
            adjustment=adjustment,  # type: ignore[arg-type]
        ),
    ]


class FakeCursor:
    """BaoStock cursor with observable exhaustion and optional mid-stream failure."""

    def __init__(
        self,
        data: list[list[str]],
        fail_after: int | None = None,
        row_error_code: str | None = None,
    ) -> None:
        self.data = [list(row) for row in data]
        self.fail_after = fail_after
        self.row_error_code = row_error_code
        self.error_code = "0"
        self.error_msg = "success"
        self.next_calls = 0
        self.row_calls = 0
        self._position = -1

    def next(self) -> bool:
        if self.row_error_code is not None:
            self.error_code = "0"
        call_index = self.next_calls
        self.next_calls += 1
        if self.fail_after is not None and call_index >= self.fail_after:
            self.error_code = "cursor-failed"
            self.error_msg = "private cursor detail"
            return False
        if call_index >= len(self.data):
            return False
        self._position = call_index
        return True

    def get_row_data(self) -> list[str]:
        if not 0 <= self._position < len(self.data):
            raise AssertionError("get_row_data called without a current row")
        self.row_calls += 1
        values = list(self.data[self._position])
        if self.row_error_code is not None:
            self.error_code = self.row_error_code
        return values


def successful_sdk(
    monkeypatch: pytest.MonkeyPatch, cursor: FakeCursor
) -> tuple[Mock, Mock, Mock]:
    login = Mock(return_value=SimpleNamespace(error_code="0", error_msg="success"))
    logout = Mock(return_value=SimpleNamespace(error_code="0", error_msg="success"))
    query = Mock(return_value=cursor)
    monkeypatch.setattr(adapter.bs, "login", login)
    monkeypatch.setattr(adapter.bs, "logout", logout)
    monkeypatch.setattr(adapter.bs, "query_history_k_data_plus", query)
    return login, logout, query


def test_a_share_stock_uses_anonymous_session_qfq_and_explicit_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(rows())
    login, logout, query = successful_sdk(monkeypatch, cursor)

    result = adapter.BaoStockOhlcvProvider().fetch_daily(
        A_STOCK, date(2026, 1, 2), date(2026, 1, 3), "qfq"
    )

    login.assert_called_once_with()
    logout.assert_called_once_with()
    query.assert_called_once_with(
        "sh.600000",
        FIELDS,
        start_date="2026-01-02",
        end_date="2026-01-03",
        frequency="d",
        adjustflag="2",
    )
    assert result == expected_bars()
    assert cursor.next_calls == 3
    assert cursor.row_calls == 2
    assert isinstance(adapter.BaoStockOhlcvProvider(), OhlcvProvider)


def test_csi300_index_uses_unadjusted_flag_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(rows())
    _, _, query = successful_sdk(monkeypatch, cursor)
    csi300 = instrument(symbol="000300.SH", instrument_type="index", provider_symbol="000300")

    result = adapter.BaoStockOhlcvProvider().fetch_daily(
        csi300, date(2026, 1, 2), date(2026, 1, 3), "none"
    )

    query.assert_called_once_with(
        "sh.000300",
        FIELDS,
        start_date="2026-01-02",
        end_date="2026-01-03",
        frequency="d",
        adjustflag="3",
    )
    assert result == expected_bars("none")


@pytest.mark.parametrize("provider_symbol", ["sh.600000", "SH600000", "600000.SH"])
def test_baostock_symbol_conversion_is_explicit_and_safe(
    monkeypatch: pytest.MonkeyPatch, provider_symbol: str
) -> None:
    _, _, query = successful_sdk(monkeypatch, FakeCursor([]))

    assert adapter.BaoStockOhlcvProvider().fetch_daily(
        instrument(provider_symbol=provider_symbol),
        None,
        date(2026, 1, 3),
        "qfq",
    ) == []
    assert query.call_args.args[0] == "sh.600000"
    assert query.call_args.kwargs["start_date"] == "1970-01-01"


def test_empty_cursor_returns_empty_and_still_logs_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor([])
    login, logout, _ = successful_sdk(monkeypatch, cursor)

    assert adapter.BaoStockOhlcvProvider().fetch_daily(
        A_STOCK, None, date(2026, 1, 3), "qfq"
    ) == []
    assert cursor.next_calls == 1
    assert cursor.row_calls == 0
    login.assert_called_once_with()
    logout.assert_called_once_with()


@pytest.mark.parametrize(
    "bad_row",
    [
        ["not-a-date", "9", "12", "8", "11", "1000", "11000"],
        ["2026-01-02", "nan", "12", "8", "11", "1000", "11000"],
        ["2026-01-02", "9", "12", "8", "11", "", "11000"],
        ["2026-01-02", "9", "12", "8", "11", "-1", "11000"],
        ["2026-01-02", "13", "12", "8", "11", "1000", "11000"],
        ["2026-01-02", "9", "12"],
    ],
    ids=["date", "nan", "missing-volume", "negative-volume", "ohlc", "short-row"],
)
def test_malformed_cursor_rows_raise_and_logout(
    monkeypatch: pytest.MonkeyPatch, bad_row: list[str]
) -> None:
    _, logout, _ = successful_sdk(monkeypatch, FakeCursor([bad_row]))

    with pytest.raises(ProviderDataInvalid):
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )
    logout.assert_called_once_with()


def test_duplicate_dates_reject_complete_cursor_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = rows()[0]
    _, logout, _ = successful_sdk(monkeypatch, FakeCursor([duplicate, duplicate]))

    with pytest.raises(ProviderDataInvalid, match="Duplicate"):
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )
    logout.assert_called_once_with()


def test_login_and_query_failures_are_typed_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = Mock(return_value=SimpleNamespace(error_code="denied", error_msg="private"))
    logout = Mock(return_value=SimpleNamespace(error_code="0", error_msg="success"))
    query = Mock()
    monkeypatch.setattr(adapter.bs, "login", login)
    monkeypatch.setattr(adapter.bs, "logout", logout)
    monkeypatch.setattr(adapter.bs, "query_history_k_data_plus", query)

    with pytest.raises(ProviderUnavailable) as login_error:
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )
    assert "private" not in str(login_error.value)
    query.assert_not_called()

    login.return_value = SimpleNamespace(error_code="0", error_msg="success")
    query.return_value = SimpleNamespace(error_code="query-private", next=Mock())
    with pytest.raises(ProviderUnavailable) as query_error:
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )
    assert "query-private" not in str(query_error.value)
    logout.assert_called_once_with()


def test_cursor_failure_after_a_row_never_returns_partial_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(rows(), fail_after=1)
    _, logout, _ = successful_sdk(monkeypatch, cursor)

    with pytest.raises(ProviderUnavailable) as error:
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )
    assert "private cursor detail" not in str(error.value)
    assert cursor.row_calls == 1
    logout.assert_called_once_with()


def test_row_retrieval_status_failure_rejects_valid_looking_row_and_logs_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(rows(), row_error_code="row-private")
    _, logout, _ = successful_sdk(monkeypatch, cursor)

    with pytest.raises(ProviderUnavailable) as error:
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )
    assert "row-private" not in str(error.value)
    assert cursor.row_calls == 1
    logout.assert_called_once_with()


@pytest.mark.parametrize(
    ("candidate", "adjustment"),
    [
        (A_STOCK, "none"),
        (instrument(instrument_type="index", provider_symbol="000300"), "qfq"),
        (instrument(instrument_type="index", provider_symbol="399300"), "none"),
        (instrument(instrument_type="etf"), "qfq"),
        (instrument(market="hk_stock"), "qfq"),
        (instrument(exchange="BSE", provider_symbol="830001"), "qfq"),
    ],
    ids=["stock-none", "index-qfq", "other-index", "etf", "hk", "beijing"],
)
def test_unsupported_combinations_fail_before_login(
    monkeypatch: pytest.MonkeyPatch,
    candidate: InstrumentDTO,
    adjustment: str,
) -> None:
    login = Mock()
    monkeypatch.setattr(adapter.bs, "login", login)

    with pytest.raises(ProviderCompatibilityError):
        adapter.BaoStockOhlcvProvider().fetch_daily(
            candidate, None, date(2026, 1, 3), adjustment  # type: ignore[arg-type]
        )
    login.assert_not_called()


@pytest.mark.parametrize("symbol", ["600000 OR 1=1", "", "60000", "sz.600000"])
def test_invalid_or_mismatched_symbols_fail_before_login(
    monkeypatch: pytest.MonkeyPatch, symbol: str
) -> None:
    login = Mock()
    monkeypatch.setattr(adapter.bs, "login", login)

    with pytest.raises(ProviderDataInvalid):
        adapter.BaoStockOhlcvProvider().fetch_daily(
            instrument(provider_symbol=symbol), None, date(2026, 1, 3), "qfq"
        )
    login.assert_not_called()


def test_sdk_exceptions_are_mapped_and_logout_does_not_mask_data_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter.bs, "login", Mock(side_effect=OSError("private login")))
    with pytest.raises(ProviderUnavailable) as login_error:
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )
    assert "private login" not in str(login_error.value)

    _, logout, _ = successful_sdk(monkeypatch, FakeCursor([["bad"]]))
    logout.side_effect = OSError("private logout")
    with pytest.raises(ProviderDataInvalid):
        adapter.BaoStockOhlcvProvider().fetch_daily(
            A_STOCK, None, date(2026, 1, 3), "qfq"
        )


def test_baostock_sessions_are_serialized_across_provider_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_query_entered = Event()
    second_query_entered = Event()
    second_started = Event()
    release_first_query = Event()
    state_lock = Lock()
    active = 0
    max_active = 0
    query_calls = 0
    errors: list[BaseException] = []

    def login() -> SimpleNamespace:
        return SimpleNamespace(error_code="0", error_msg="success")

    def logout() -> SimpleNamespace:
        return SimpleNamespace(error_code="0", error_msg="success")

    def query(*args: object, **kwargs: object) -> FakeCursor:
        nonlocal active, max_active, query_calls
        with state_lock:
            active += 1
            query_calls += 1
            call_number = query_calls
            max_active = max(max_active, active)
            if call_number == 1:
                first_query_entered.set()
            elif call_number == 2:
                second_query_entered.set()
        try:
            if call_number == 1:
                assert release_first_query.wait(timeout=2)
            return FakeCursor([])
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(adapter.bs, "login", login)
    monkeypatch.setattr(adapter.bs, "logout", logout)
    monkeypatch.setattr(adapter.bs, "query_history_k_data_plus", query)

    def fetch(second: bool = False) -> None:
        try:
            if second:
                second_started.set()
            adapter.BaoStockOhlcvProvider().fetch_daily(
                A_STOCK, None, date(2026, 1, 3), "qfq"
            )
        except BaseException as error:  # pragma: no cover - reported below
            with state_lock:
                errors.append(error)

    first = Thread(target=fetch)
    second = Thread(target=fetch, args=(True,))
    first.start()
    try:
        assert first_query_entered.wait(timeout=1)
        second.start()
        assert second_started.wait(timeout=1)
        assert not second_query_entered.wait(timeout=0.1)
    finally:
        release_first_query.set()
        first.join(timeout=2)
        if second.is_alive() or second_started.is_set():
            second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert query_calls == 2
    assert max_active == 1
