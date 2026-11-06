"""Offline normalization tests for current AKShare A-share universes."""

from datetime import date, datetime
from unittest.mock import Mock

import pandas as pd
import pytest

import app.providers.a_share_universes as adapter
from app.domain.dto import InstrumentDTO
from app.providers.base import UniverseProvider
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderUnavailable,
)


def csi_row(
    code: str = "600519",
    *,
    name: str = "贵州茅台",
    exchange: str = "上海证券交易所",
    effective_date: object = date(2026, 1, 30),
) -> dict[str, object]:
    return {
        "日期": effective_date,
        "指数代码": "000300",
        "指数名称": "沪深300",
        "成分券代码": code,
        "成分券名称": name,
        "交易所": exchange,
    }


def board_row(code: str = "688981", *, name: str = "中芯国际") -> dict[str, object]:
    return {
        "证券代码": code,
        "证券简称": name,
        "证券全称": f"{name}股份有限公司",
        "上市日期": date(2020, 7, 22),
    }


def sz_board_row(code: str, *, name: str) -> dict[str, object]:
    return {
        "板块": "创业板" if code.startswith("30") else "主板",
        "A股代码": code,
        "A股简称": name,
        "A股上市日期": "2020-01-01",
    }


def patch_reader(
    monkeypatch: pytest.MonkeyPatch, name: str, frame: object
) -> Mock:
    call = Mock(return_value=frame)
    monkeypatch.setattr(adapter.ak, name, call)
    return call


@pytest.fixture(autouse=True)
def forbid_legacy_live_quote_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("stock_kc_a_spot_em", "stock_sz_a_spot_em"):
        monkeypatch.setattr(
            adapter.ak,
            name,
            Mock(side_effect=AssertionError("live quote readers are forbidden")),
        )


def test_csi300_uses_official_reader_and_builds_current_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            csi_row(),
            csi_row(
                "000001",
                name="平安银行",
                exchange="深圳证券交易所",
                effective_date=datetime(2026, 1, 30),
            ),
            csi_row("688981", name="中芯国际", exchange="SSE"),
        ]
    )
    original = frame.copy(deep=True)
    call = patch_reader(monkeypatch, "index_stock_cons_csindex", frame)
    provider = adapter.AkshareUniverseProvider()

    snapshot = provider.fetch_universe("csi300")

    call.assert_called_once_with(symbol="000300")
    assert isinstance(provider, UniverseProvider)
    assert snapshot.universe_code == "csi300"
    assert snapshot.source == "akshare"
    assert snapshot.effective_date == date(2026, 1, 30)
    assert [item.symbol for item in snapshot.members] == [
        "600519.SH",
        "000001.SZ",
        "688981.SH",
    ]
    assert [item.exchange for item in snapshot.members] == ["SSE", "SZSE", "SSE"]
    assert [item.provider_symbol for item in snapshot.members] == [
        "600519",
        "000001",
        "688981",
    ]
    assert all(item.market == "a_share" for item in snapshot.members)
    assert all(item.currency == "CNY" for item in snapshot.members)
    assert all(item.timezone == "Asia/Shanghai" for item in snapshot.members)
    assert all(item.instrument_type == "stock" for item in snapshot.members)
    assert snapshot.related_instruments == (
        InstrumentDTO(
            symbol="000300.SH",
            name="CSI 300 Index",
            market="a_share",
            exchange="SSE",
            currency="CNY",
            timezone="Asia/Shanghai",
            instrument_type="index",
            provider_symbol="000300",
        ),
    )
    assert "000300.SH" not in {item.symbol for item in snapshot.members}
    pd.testing.assert_frame_equal(frame, original)


def test_star_uses_dedicated_shanghai_star_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = patch_reader(
        monkeypatch,
        "stock_info_sh_name_code",
        pd.DataFrame(
            [board_row(), board_row("689009", name="九号公司")]
        ),
    )

    snapshot = adapter.AkshareUniverseProvider().fetch_universe("star_market")

    call.assert_called_once_with(symbol="科创板")
    assert snapshot.universe_code == "star_market"
    assert snapshot.effective_date is None
    assert snapshot.related_instruments == ()
    assert [(item.symbol, item.name) for item in snapshot.members] == [
        ("688981.SH", "中芯国际"),
        ("689009.SH", "九号公司"),
    ]


def test_chinext_filters_shenzhen_list_to_only_the_30xxxx_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = patch_reader(
        monkeypatch,
        "stock_info_sz_name_code",
        pd.DataFrame(
            [
                sz_board_row("000001", name="平安银行"),
                sz_board_row("200002", name="万科B"),
                sz_board_row("002594", name="比亚迪"),
                sz_board_row("300750", name="宁德时代"),
                sz_board_row("301269", name="华大九天"),
            ]
        ),
    )

    snapshot = adapter.AkshareUniverseProvider().fetch_universe("chinext")

    call.assert_called_once_with(symbol="A股列表")
    assert snapshot.universe_code == "chinext"
    assert snapshot.effective_date is None
    assert snapshot.related_instruments == ()
    assert [item.symbol for item in snapshot.members] == ["300750.SZ", "301269.SZ"]
    assert all(item.exchange == "SZSE" for item in snapshot.members)


@pytest.mark.parametrize(
    ("exchange", "code", "suffix"),
    [
        ("SH", "600000", "SH"),
        ("XSHG", "601318", "SH"),
        ("Shanghai Stock Exchange", "603259", "SH"),
        ("SZ", "000001", "SZ"),
        ("SZSE", "002594", "SZ"),
        ("Shenzhen Stock Exchange", "300750", "SZ"),
    ],
)
def test_csi300_accepts_only_explicit_known_exchange_spellings(
    monkeypatch: pytest.MonkeyPatch, exchange: str, code: str, suffix: str
) -> None:
    patch_reader(
        monkeypatch,
        "index_stock_cons_csindex",
        pd.DataFrame([csi_row(code, exchange=exchange)]),
    )

    snapshot = adapter.AkshareUniverseProvider().fetch_universe("csi300")

    assert snapshot.members[0].symbol == f"{code}.{suffix}"


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "empty"),
        ([csi_row("60051")], "code"),
        ([csi_row("60051A")], "code"),
        ([csi_row(600519)], "code"),
        ([csi_row(name=" ")], "name"),
        ([csi_row(name=float("nan"))], "name"),
        ([csi_row(exchange="Beijing Stock Exchange")], "exchange"),
        ([csi_row("000001", exchange="SSE")], "exchange"),
        ([csi_row(), csi_row()], "Duplicate"),
        ([csi_row(effective_date="not-a-date")], "date"),
        (
            [
                csi_row(),
                csi_row(
                    "000001",
                    exchange="SZSE",
                    effective_date=date(2026, 1, 29),
                ),
            ],
            "date",
        ),
    ],
    ids=[
        "empty",
        "short-code",
        "nonnumeric-code",
        "non-string-code",
        "blank-name",
        "nan-name",
        "unknown-exchange",
        "exchange-code-mismatch",
        "duplicate",
        "bad-date",
        "mixed-dates",
    ],
)
def test_csi300_rejects_empty_malformed_duplicate_and_ambiguous_data(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]], message: str
) -> None:
    patch_reader(
        monkeypatch, "index_stock_cons_csindex", pd.DataFrame(rows)
    )

    with pytest.raises(ProviderDataInvalid, match=message):
        adapter.AkshareUniverseProvider().fetch_universe("csi300")


@pytest.mark.parametrize("frame", [None, [], {"证券代码": "688981"}])
def test_non_dataframe_responses_are_rejected(
    monkeypatch: pytest.MonkeyPatch, frame: object
) -> None:
    patch_reader(monkeypatch, "stock_info_sh_name_code", frame)

    with pytest.raises(ProviderDataInvalid, match="DataFrame"):
        adapter.AkshareUniverseProvider().fetch_universe("star_market")


@pytest.mark.parametrize(
    ("universe_code", "reader_name", "rows"),
    [
        ("star_market", "stock_info_sh_name_code", []),
        ("star_market", "stock_info_sh_name_code", [board_row("600519")]),
        ("star_market", "stock_info_sh_name_code", [board_row(), board_row()]),
        ("chinext", "stock_info_sz_name_code", [
            sz_board_row("000001", name="平安银行"),
            sz_board_row("200002", name="万科B"),
        ]),
        (
            "chinext",
            "stock_info_sz_name_code",
            [
                sz_board_row("300750", name="宁德时代"),
                sz_board_row("300750", name="duplicate"),
            ],
        ),
        ("chinext", "stock_info_sz_name_code", [
            sz_board_row("not-a-code", name="bad")
        ]),
    ],
    ids=[
        "star-empty",
        "star-wrong-board",
        "star-duplicate",
        "chinext-empty-after-filter",
        "chinext-duplicate",
        "chinext-malformed-code",
    ],
)
def test_board_lists_fail_instead_of_returning_partial_or_empty_membership(
    monkeypatch: pytest.MonkeyPatch,
    universe_code: str,
    reader_name: str,
    rows: list[dict[str, object]],
) -> None:
    patch_reader(monkeypatch, reader_name, pd.DataFrame(rows))

    with pytest.raises(ProviderDataInvalid):
        adapter.AkshareUniverseProvider().fetch_universe(universe_code)


@pytest.mark.parametrize(
    ("rows", "column"),
    [
        ([csi_row()], "成分券代码"),
        ([csi_row()], "成分券名称"),
        ([csi_row()], "交易所"),
        ([csi_row()], "日期"),
        ([board_row()], "证券代码"),
        ([board_row()], "证券简称"),
        ([sz_board_row("300750", name="宁德时代")], "A股代码"),
        ([sz_board_row("300750", name="宁德时代")], "A股简称"),
    ],
)
def test_missing_required_columns_are_not_treated_as_empty_data(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
    column: str,
) -> None:
    row = dict(rows[0])
    del row[column]
    is_csi = column in {"成分券代码", "成分券名称", "交易所", "日期"}
    is_sz = column in {"A股代码", "A股简称"}
    reader_name = (
        "index_stock_cons_csindex"
        if is_csi
        else "stock_info_sz_name_code" if is_sz else "stock_info_sh_name_code"
    )
    universe_code = "csi300" if is_csi else "chinext" if is_sz else "star_market"
    patch_reader(monkeypatch, reader_name, pd.DataFrame([row]))

    with pytest.raises(ProviderDataInvalid, match=column):
        adapter.AkshareUniverseProvider().fetch_universe(universe_code)


def test_upstream_failure_is_sanitized_and_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter.ak,
        "index_stock_cons_csindex",
        Mock(side_effect=RuntimeError("private upstream detail")),
    )

    with pytest.raises(ProviderUnavailable) as captured:
        adapter.AkshareUniverseProvider().fetch_universe("csi300")
    assert "private upstream detail" not in str(captured.value)


def test_unknown_universe_fails_before_any_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [Mock() for _ in range(3)]
    for name, call in zip(
        ("index_stock_cons_csindex", "stock_info_sh_name_code", "stock_info_sz_name_code"),
        calls,
        strict=True,
    ):
        monkeypatch.setattr(adapter.ak, name, call)

    with pytest.raises(ProviderCompatibilityError):
        adapter.AkshareUniverseProvider().fetch_universe("CSI300")
    assert all(call.call_count == 0 for call in calls)
