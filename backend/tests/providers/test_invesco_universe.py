"""Fixture-only Invesco QQQ current-holdings parsing tests."""

import json
from datetime import date
from unittest.mock import Mock

import pytest

import app.providers.invesco_universe as adapter
from app.providers.base import UniverseProvider
from app.providers.errors import ProviderCompatibilityError, ProviderDataInvalid

EFFECTIVE_DATE = "2026-01-30"
_DEFAULT_NAME = object()


def holding(
    ticker: object,
    security_type: object = "COM",
    *,
    name: object = _DEFAULT_NAME,
    effective_date: object = EFFECTIVE_DATE,
) -> dict[str, object]:
    if name is _DEFAULT_NAME:
        name = f"{ticker} Incorporated"
    return {
        "effectiveDate": effective_date,
        "ticker": ticker,
        "securityTypeCode": security_type,
        "name": name,
    }


def payload() -> dict[str, object]:
    return {
        "holdings": [
            holding("AAPL", name="Apple Inc."),
            holding("GOOG", name="Alphabet Inc. Class C"),
            holding("GOOGL", name="Alphabet Inc. Class A"),
            holding("ADR1", "ADR", name="Fixture ADR"),
            holding("DEP1", "DRNY", name="Fixture Depositary Receipt"),
            holding(None, "CURR", name="US Dollar"),
            holding("COLLATERAL", "CURRCOL", name="Collateral"),
            holding("NQH6", "IFUT", name="Nasdaq Future"),
            holding(None, "SYN", name="Synthetic Cash"),
        ]
    }


def test_parser_keeps_only_verified_equity_types_and_distinct_share_classes() -> None:
    members = adapter.parse_qqq_holdings(payload())

    assert [item.symbol for item in members] == [
        "AAPL",
        "GOOG",
        "GOOGL",
        "ADR1",
        "DEP1",
    ]
    assert len(members) == len(payload()["holdings"]) - 4
    assert {item.symbol for item in members}.isdisjoint(
        {"COLLATERAL", "NQH6", "CURR", "SYN"}
    )
    assert all(item.market == "us_stock" for item in members)
    assert all(item.exchange == "NASDAQ" for item in members)
    assert all(item.currency == "USD" for item in members)
    assert all(item.timezone == "America/New_York" for item in members)
    assert all(item.instrument_type == "stock" for item in members)


def test_parser_supports_verified_production_issuer_name_shape() -> None:
    row = {
        "effectiveDate": EFFECTIVE_DATE,
        "ticker": "NVDA",
        "securityTypeCode": "COM",
        "issuerName": "NVIDIA Corp",
    }

    members = adapter.parse_qqq_holdings({"holdings": [row]})

    assert len(members) == 1
    assert members[0].symbol == "NVDA"
    assert members[0].name == "NVIDIA Corp"


def test_parser_supports_security_name_and_preserves_canonical_yahoo_mapping() -> None:
    row = holding("BRK/B", name="Berkshire Hathaway Class B")
    del row["name"]
    row["securityName"] = "Berkshire Hathaway Class B"

    members = adapter.parse_qqq_holdings({"holdings": [row]})

    assert len(members) == 1
    assert members[0].symbol == "BRK.B"
    assert members[0].provider_symbol == "BRK-B"
    assert members[0].name == "Berkshire Hathaway Class B"


@pytest.mark.parametrize("security_type", ["CURR", "CURRCOL", "IFUT", "SYN"])
def test_known_non_equity_rows_may_have_no_ticker(security_type: str) -> None:
    rows = [holding("AAPL"), holding(None, security_type)]

    assert [item.symbol for item in adapter.parse_qqq_holdings({"holdings": rows})] == [
        "AAPL"
    ]


@pytest.mark.parametrize("security_type", ["PREF", "UNKNOWN", "", None])
def test_unknown_security_types_fail_instead_of_silent_filtering(
    security_type: object,
) -> None:
    with pytest.raises(ProviderDataInvalid, match="security type"):
        adapter.parse_qqq_holdings(
            {"holdings": [holding("AAPL"), holding("OTHER", security_type)]}
        )


@pytest.mark.parametrize("ticker", [None, "", " ", "BAD TICKER", 123])
def test_equity_missing_or_invalid_ticker_fails(ticker: object) -> None:
    with pytest.raises(ProviderDataInvalid):
        adapter.parse_qqq_holdings({"holdings": [holding(ticker)]})


@pytest.mark.parametrize("name", [None, "", " ", 123])
def test_equity_missing_or_invalid_name_fails(name: object) -> None:
    with pytest.raises(ProviderDataInvalid):
        adapter.parse_qqq_holdings({"holdings": [holding("AAPL", name=name)]})


@pytest.mark.parametrize(
    "rows",
    [
        [holding("AAPL"), holding("AAPL")],
        [holding("BRK.B"), holding("BRK-B")],
    ],
    ids=["exact", "normalized-share-class"],
)
def test_duplicate_equity_tickers_fail(rows: list[dict[str, object]]) -> None:
    with pytest.raises(ProviderDataInvalid, match="Duplicate"):
        adapter.parse_qqq_holdings({"holdings": rows})


@pytest.mark.parametrize("effective_date", ["", "31/01/2026", "2026-02-30", None])
def test_malformed_effective_date_fails_even_though_parser_returns_instruments(
    effective_date: object,
) -> None:
    with pytest.raises(ProviderDataInvalid, match="effective date"):
        adapter.parse_qqq_holdings(
            {"holdings": [holding("AAPL", effective_date=effective_date)]}
        )


def test_ambiguous_effective_dates_fail() -> None:
    rows = [
        holding("AAPL", effective_date="2026-01-30"),
        holding("MSFT", effective_date="2026-01-31"),
    ]

    with pytest.raises(ProviderDataInvalid, match="effective date"):
        adapter.parse_qqq_holdings({"holdings": rows})


def test_top_level_effective_date_can_apply_to_all_rows() -> None:
    rows = [holding("AAPL"), holding("GOOG")]
    for row in rows:
        del row["effectiveDate"]

    members = adapter.parse_qqq_holdings(
        {"effectiveDate": "01/30/2026", "holdings": rows}
    )

    assert [item.symbol for item in members] == ["AAPL", "GOOG"]


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"holdings": []},
        {"holdings": {}},
        {"holdings": [holding(None, "CURR")]},
        {"holdings": ["not-a-mapping"]},
    ],
    ids=["missing", "empty", "wrong-container", "no-equity", "wrong-row"],
)
def test_empty_or_structurally_invalid_payload_fails(value: dict[str, object]) -> None:
    with pytest.raises(ProviderDataInvalid):
        adapter.parse_qqq_holdings(value)


def test_provider_downloads_bounded_verified_json_and_builds_current_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = json.dumps(payload()).encode("utf-8")
    download = Mock(return_value=content)
    monkeypatch.setattr(adapter, "fetch_bytes", download)
    provider = adapter.InvescoUniverseProvider()

    snapshot = provider.fetch_universe("nasdaq100")

    download.assert_called_once_with(
        "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/"
        "holdings/fund?idType=ticker&interval=monthly&productType=ETF",
        max_bytes=adapter.QQQ_MAX_BYTES,
        timeout=adapter.QQQ_TIMEOUT_SECONDS,
        expected_content_type="application/json",
    )
    assert download.call_args.kwargs["max_bytes"] > 0
    assert download.call_args.kwargs["timeout"] > 0
    assert isinstance(provider, UniverseProvider)
    assert snapshot.universe_code == "nasdaq100"
    assert snapshot.source == "invesco"
    assert snapshot.effective_date == date(2026, 1, 30)
    assert [item.symbol for item in snapshot.members] == [
        "AAPL",
        "GOOG",
        "GOOGL",
        "ADR1",
        "DEP1",
    ]
    assert len(snapshot.related_instruments) == 1
    index = snapshot.related_instruments[0]
    assert index.symbol == "^NDX"
    assert index.provider_symbol == "^NDX"
    assert index.instrument_type == "index"
    assert index not in snapshot.members


@pytest.mark.parametrize(
    "content",
    [b"", b"not-json", b"[]", b'{"holdings": null}'],
    ids=["empty", "bad-json", "wrong-root", "missing-list"],
)
def test_invalid_download_content_fails(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    monkeypatch.setattr(adapter, "fetch_bytes", Mock(return_value=content))

    with pytest.raises(ProviderDataInvalid):
        adapter.InvescoUniverseProvider().fetch_universe("nasdaq100")


def test_unknown_universe_fails_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = Mock()
    monkeypatch.setattr(adapter, "fetch_bytes", download)

    with pytest.raises(ProviderCompatibilityError):
        adapter.InvescoUniverseProvider().fetch_universe("NASDAQ100")
    download.assert_not_called()
