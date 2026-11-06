"""Fixture-only iShares SOXX current-holdings CSV tests."""

from datetime import date
from unittest.mock import Mock

import pytest

import app.providers.ishares_soxx as adapter
from app.providers.base import UniverseProvider
from app.providers.errors import ProviderCompatibilityError, ProviderDataInvalid

SOXX_URL = (
    "https://www.ishares.com/us/products/239705/ishares-semiconductor-etf/"
    "latest-holdings.csv"
)


def csv_content(
    rows: list[list[str]] | None = None,
    *,
    holdings_date: str = "Jan 30, 2026",
) -> bytes:
    holdings_rows = rows or [
        ["NVDA", "NVIDIA Corp", "Information Technology", "Equity", "NASDAQ"],
        ["AMD", "Advanced Micro Devices, Inc.", "Information Technology", "Equity", "NASDAQ"],
        ["TSM", "Taiwan Semiconductor ADR", "Information Technology", "Equity", "NYSE"],
        ["-", "US Dollar", "-", "Cash and/or Derivatives", "-"],
        ["NQH6", "Nasdaq Future", "-", "Futures", "-"],
        ["-", "Collateral", "-", "Collateral", "-"],
    ]
    lines = [
        "iShares Semiconductor ETF",
        f'Fund Holdings as of,"{holdings_date}"',
        "Inception Date,\"Jul 10, 2001\"",
        "Ticker,Name",
        "-,-",
        "Ticker,Name,Sector,Asset Class,Exchange",
        *(','.join(f'"{value}"' for value in row) for row in holdings_rows),
        "",
    ]
    return ("﻿" + "\n".join(lines)).encode("utf-8")


def test_parser_locates_real_header_and_keeps_equity_rows_only() -> None:
    members = adapter.parse_soxx_holdings(csv_content())

    assert [item.symbol for item in members] == ["NVDA", "AMD", "TSM"]
    assert len(members) == 3
    assert [item.name for item in members] == [
        "NVIDIA Corp",
        "Advanced Micro Devices, Inc.",
        "Taiwan Semiconductor ADR",
    ]
    assert [item.exchange for item in members] == ["NASDAQ", "NASDAQ", "NYSE"]
    assert all(item.market == "us_stock" for item in members)
    assert all(item.currency == "USD" for item in members)
    assert all(item.timezone == "America/New_York" for item in members)
    assert all(item.instrument_type == "stock" for item in members)
    assert all(item.provider_symbol == item.symbol for item in members)


def test_parser_preserves_canonical_and_yahoo_share_class_symbols() -> None:
    content = csv_content(
        [["BRK/B", "Berkshire Hathaway Class B", "Financials", "Equity", "NYSE"]]
    )

    members = adapter.parse_soxx_holdings(content)

    assert len(members) == 1
    assert members[0].symbol == "BRK.B"
    assert members[0].provider_symbol == "BRK-B"


def test_non_equity_rows_do_not_require_valid_equity_identifiers() -> None:
    content = csv_content(
        [
            ["NVDA", "NVIDIA Corp", "Technology", "Equity", "NASDAQ"],
            ["", "", "", "Cash and/or Derivatives", ""],
            ["not a ticker", "", "", "Collateral", ""],
        ]
    )

    assert [item.symbol for item in adapter.parse_soxx_holdings(content)] == ["NVDA"]


@pytest.mark.parametrize("ticker", ["", " ", "-", "BAD TICKER"])
def test_missing_or_invalid_equity_ticker_fails(ticker: str) -> None:
    content = csv_content([[ticker, "Valid Name", "Technology", "Equity", "NASDAQ"]])

    with pytest.raises(ProviderDataInvalid):
        adapter.parse_soxx_holdings(content)


@pytest.mark.parametrize("column", ["Name", "Exchange"])
def test_missing_equity_name_or_exchange_fails(column: str) -> None:
    row = ["NVDA", "NVIDIA Corp", "Technology", "Equity", "NASDAQ"]
    row[1 if column == "Name" else 4] = " "
    content = csv_content([row])

    with pytest.raises(ProviderDataInvalid, match=column.lower()):
        adapter.parse_soxx_holdings(content)


@pytest.mark.parametrize(
    "rows",
    [
        [
            ["NVDA", "NVIDIA One", "Technology", "Equity", "NASDAQ"],
            ["NVDA", "NVIDIA Two", "Technology", "Equity", "NASDAQ"],
        ],
        [
            ["BRK.B", "Class B One", "Financials", "Equity", "NYSE"],
            ["BRK-B", "Class B Two", "Financials", "Equity", "NYSE"],
        ],
    ],
    ids=["exact", "normalized-share-class"],
)
def test_duplicate_equity_tickers_fail(rows: list[list[str]]) -> None:
    with pytest.raises(ProviderDataInvalid, match="Duplicate"):
        adapter.parse_soxx_holdings(csv_content(rows))


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xff\xfe",
        csv_content().replace(
            b"Ticker,Name,Sector,Asset Class,Exchange", b"Ticker,Name,Sector,Class,Exchange"
        ),
        csv_content([["-", "Cash", "-", "Cash and/or Derivatives", "-"]]),
    ],
    ids=["empty", "invalid-utf8", "missing-header", "no-equity"],
)
def test_empty_malformed_or_equity_free_csv_fails(content: bytes) -> None:
    with pytest.raises(ProviderDataInvalid):
        adapter.parse_soxx_holdings(content)


def test_provider_downloads_bounded_official_csv_and_builds_current_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = Mock(return_value=csv_content())
    monkeypatch.setattr(adapter, "fetch_bytes", download)
    provider = adapter.IsharesSoxxUniverseProvider()

    snapshot = provider.fetch_universe("soxx")

    download.assert_called_once_with(
        SOXX_URL,
        max_bytes=adapter.SOXX_MAX_BYTES,
        timeout=adapter.SOXX_TIMEOUT_SECONDS,
        expected_content_type="text/csv",
    )
    assert download.call_args.kwargs["max_bytes"] > 0
    assert download.call_args.kwargs["timeout"] > 0
    assert isinstance(provider, UniverseProvider)
    assert snapshot.universe_code == "soxx"
    assert snapshot.source == "ishares"
    assert snapshot.effective_date == date(2026, 1, 30)
    assert [item.symbol for item in snapshot.members] == ["NVDA", "AMD", "TSM"]
    assert len(snapshot.related_instruments) == 1
    etf = snapshot.related_instruments[0]
    assert etf.symbol == "SOXX"
    assert etf.provider_symbol == "SOXX"
    assert etf.instrument_type == "etf"
    assert etf not in snapshot.members


@pytest.mark.parametrize("holdings_date", ["", "30 Jan 2026", "Feb 30, 2026"])
def test_malformed_holdings_date_fails_snapshot(
    monkeypatch: pytest.MonkeyPatch, holdings_date: str
) -> None:
    monkeypatch.setattr(
        adapter,
        "fetch_bytes",
        Mock(return_value=csv_content(holdings_date=holdings_date)),
    )

    with pytest.raises(ProviderDataInvalid, match="effective date"):
        adapter.IsharesSoxxUniverseProvider().fetch_universe("soxx")


def test_unknown_universe_fails_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = Mock()
    monkeypatch.setattr(adapter, "fetch_bytes", download)

    with pytest.raises(ProviderCompatibilityError):
        adapter.IsharesSoxxUniverseProvider().fetch_universe("SOXX")
    download.assert_not_called()
