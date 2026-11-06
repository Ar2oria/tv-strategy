"""Fixture-only HSTECH factsheet parsing and snapshot preservation tests."""

from collections.abc import Sequence
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.providers.hstech_universe as universe_adapter
from app.db.database import SessionFactory
from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.providers.base import UniverseProvider
from app.providers.errors import (
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderUnavailable,
)
from app.providers.hstech_parser import parse_hstech_constituents
from app.repositories.instruments import InstrumentRepository

Row = tuple[str, str, str, str]
DEFAULT_ROWS: tuple[Row, ...] = (
    ("0700", "Tencent Holdings Ltd", "Information Technology", "Ordinary Shares"),
    (
        "9988",
        "Alibaba Group Holding Ltd",
        "Consumer Discretionary",
        "Other HK-listed Mainland Co.",
    ),
    (
        "1024",
        "Kuaishou Technology",
        "Communication Services",
        "Other HK-listed Mainland Co.",
    ),
)
OFFICIAL_ROWS: tuple[Row, ...] = (
    DEFAULT_ROWS[0],
    DEFAULT_ROWS[1],
    (
        "1810",
        "Xiaomi Corporation Class B",
        "Information Technology",
        "Other HK-listed Mainland Companies",
    ),
    (
        "1024",
        "Kuaishou Technology",
        "Communication Services",
        "Other HK-listed Mainland Company",
    ),
    (
        "9618",
        "JD.com Inc Class A",
        "Consumer Discretionary",
        "Other HK-listed Mainland Co.",
    ),
    (
        "3690",
        "Meituan Class B",
        "Consumer Discretionary",
        "Other HK-listed Mainland Companies",
    ),
    (
        "9888",
        "Baidu Inc Class A",
        "Communication Services",
        "Other HK-listed Mainland Co.",
    ),
    ("9999", "NetEase Inc", "Communication Services", "Ordinary Shares"),
)


def factsheet_text(
    rows: Sequence[Row] = DEFAULT_ROWS,
    *,
    declared_count: int | None = None,
    include_table: bool = True,
    include_count: bool = True,
) -> str:
    count = len(rows) if declared_count is None else declared_count
    lines = [
        "Hang Seng TECH Index",
        "As of 31 January 2026",
        "Index performance figures 4,000.00",
    ]
    if include_table:
        lines.extend(
            [
                "CONSTITUENTS",
                "Stock Code Company Name Industry Share Type Weighting (%)",
            ]
        )
        lines.extend(
            f"{code} {name} {industry} {share_type} 8.25"
            for code, name, industry, share_type in rows
        )
    if include_count:
        lines.append(f"Number of Constituents: {count}")
    lines.append("Disclaimer: fixture text only")
    return "\n".join(lines)


def test_parser_preserves_four_digit_codes_and_multi_word_names() -> None:
    members = parse_hstech_constituents(factsheet_text(), "fixture")

    assert isinstance(members, list)
    assert [(item.symbol, item.provider_symbol) for item in members] == [
        ("0700.HK", "0700.HK"),
        ("9988.HK", "9988.HK"),
        ("1024.HK", "1024.HK"),
    ]
    assert [item.name for item in members] == [row[1] for row in DEFAULT_ROWS]
    assert all(item.market == "hk_stock" for item in members)
    assert all(item.exchange == "HKEX" for item in members)
    assert all(item.currency == "HKD" for item in members)
    assert all(item.timezone == "Asia/Hong_Kong" for item in members)
    assert all(item.instrument_type == "stock" for item in members)


@pytest.mark.parametrize(
    "share_type",
    [
        "Other HK-listed Mainland Co.",
        "Other HK-listed Mainland Company",
        "Other HK-listed Mainland Companies",
    ],
)
def test_parser_supports_official_mainland_company_share_type_variants(
    share_type: str,
) -> None:
    row = (
        "9988",
        "Alibaba Group Holding Ltd",
        "Consumer Discretionary",
        share_type,
    )

    members = parse_hstech_constituents(factsheet_text([row]), "official taxonomy")

    assert [item.symbol for item in members] == ["9988.HK"]


def test_representative_full_official_table_uses_dynamic_declared_count() -> None:
    members = parse_hstech_constituents(
        factsheet_text(OFFICIAL_ROWS), "full official-table fixture"
    )

    assert len(OFFICIAL_ROWS) == 8
    assert len(members) == len(OFFICIAL_ROWS)
    assert [item.symbol for item in members] == [
        f"{row[0]}.HK" for row in OFFICIAL_ROWS
    ]
    assert [item.name for item in members] == [row[1] for row in OFFICIAL_ROWS]
    assert "1810.HK" in {item.symbol for item in members}


def test_parser_supports_current_official_isin_columns_and_total_footer() -> None:
    text = (
        "No. of Constituents 3\n"
        "CONSTITUENTS\n"
        "Stock Code ISIN CODE Company Name Industry Classification Share Type Weighting (%)\n"
        "9999 KYG6427A1022 NTES Information Technology Other HK-listed Mainland Co. 8.74\n"
        "1211 CNE100000296 BYD COMPANY Consumer Discretionary H Share 7.34\n"
        "6618 KYG5074A1004 JD HEALTH Healthcare Other HK-listed Mainland Co. 1.25\n"
        "Total 100.00\n"
        "Weightings may not add up to the total due to rounding\n"
    )

    members = parse_hstech_constituents(text, "current official layout")

    assert [item.symbol for item in members] == ["9999.HK", "1211.HK", "6618.HK"]
    assert [item.name for item in members] == ["NTES", "BYD COMPANY", "JD HEALTH"]


def test_parser_handles_tabs_nonbreaking_spaces_and_optional_weight_percent() -> None:
    text = (
        "CONSTITUENTS\n"
        "Code\tCompany Name\tIndustry\tShare Type\tWeighting\n"
        "0700\tTencent Holdings   Ltd.\tInformation Technology\t"
        "Ordinary Shares\t8.25%\n"
        "Number of Constituents: 1\n"
    )

    members = parse_hstech_constituents(text, "whitespace fixture")

    assert len(members) == 1
    assert members[0].symbol == "0700.HK"
    assert members[0].name == "Tencent Holdings Ltd."


def test_parser_supports_a_company_name_wrapped_by_pdf_extraction() -> None:
    text = (
        "CONSTITUENTS\n"
        "Stock Code Company Name Industry Share Type\n"
        "0700 Tencent Holdings\n"
        "Ltd Information Technology Ordinary Shares\n"
        "No. of Constituents: 1\n"
    )

    members = parse_hstech_constituents(text, "wrapped fixture")

    assert [item.name for item in members] == ["Tencent Holdings Ltd"]


@pytest.mark.parametrize("row_count", [1, 2, 4])
def test_parser_uses_the_declared_count_instead_of_assuming_thirty(
    row_count: int,
) -> None:
    catalog = (
        DEFAULT_ROWS
        + (("1810", "Xiaomi Corporation Class B", "Information Technology", "Other HK-listed Mainland Companies"),)
    )
    rows = catalog[:row_count]

    members = parse_hstech_constituents(factsheet_text(rows), "changed-count fixture")

    assert len(members) == row_count
    assert len({item.symbol for item in members}) == row_count


def test_parser_accepts_declared_count_before_the_table() -> None:
    text = (
        "No. of Constituents: 1\n"
        "CONSTITUENTS\n"
        "Stock Code Company Name Industry Share Type\n"
        "0700 Tencent Holdings Ltd Information Technology Ordinary Shares\n"
        "Disclaimer\n"
    )

    assert len(parse_hstech_constituents(text, "fixture")) == 1


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n",
        "Hang Seng TECH Index\nNumber of Constituents: 3\n",
        factsheet_text(include_table=False),
        factsheet_text().replace("Share Type", "Classification"),
        factsheet_text(include_count=False),
        factsheet_text(declared_count=2),
        factsheet_text(declared_count=4),
        factsheet_text(declared_count=0),
        factsheet_text().replace("Number of Constituents: 3", "Constituents: many"),
    ],
    ids=[
        "empty",
        "whitespace",
        "missing-table",
        "count-without-table",
        "missing-required-header",
        "missing-count",
        "count-too-small",
        "count-too-large",
        "zero-count",
        "malformed-count",
    ],
)
def test_missing_or_structurally_invalid_tables_and_counts_fail(text: str) -> None:
    with pytest.raises(ProviderDataInvalid):
        parse_hstech_constituents(text, "fixture")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (("700", "Tencent Holdings", "Information Technology", "Ordinary Shares"), "code|row|count"),
        (("00700", "Tencent Holdings", "Information Technology", "Ordinary Shares"), "code|row|count"),
        (("07X0", "Tencent Holdings", "Information Technology", "Ordinary Shares"), "code|row|count"),
        (("0700", " ", "Information Technology", "Ordinary Shares"), "name|row"),
        (("0700", "Tencent Holdings", "Unknown Industry", "Ordinary Shares"), "industry|row"),
        (("0700", "Tencent Holdings", "Information Technology", "Unknown Type"), "share|row"),
    ],
    ids=[
        "three-digit-code",
        "five-digit-code",
        "nonnumeric-code",
        "blank-name",
        "unknown-industry",
        "unknown-share-type",
    ],
)
def test_malformed_rows_fail_visibly(row: Row, message: str) -> None:
    with pytest.raises(ProviderDataInvalid, match=message):
        parse_hstech_constituents(factsheet_text([row]), "fixture")


@pytest.mark.parametrize(
    "declared_value",
    ["3junk", "3.5", "+3", "-3", "3 junk"],
    ids=["suffixed", "fractional", "explicit-positive", "negative", "trailing-token"],
)
def test_declared_count_requires_the_entire_value_to_be_a_positive_integer(
    declared_value: str,
) -> None:
    valid_rows = (
        ("0700", "Tencent Holdings Ltd", "Information Technology", "Ordinary Shares"),
        ("1810", "Xiaomi Corporation", "Information Technology", "Ordinary Shares"),
        ("9999", "NetEase Inc", "Communication Services", "Ordinary Shares"),
    )
    text = factsheet_text(valid_rows).replace(
        "Number of Constituents: 3",
        f"Number of Constituents: {declared_value}",
    )

    with pytest.raises(ProviderDataInvalid, match="declared constituent count"):
        parse_hstech_constituents(text, "fixture")


def test_duplicate_constituents_are_rejected_before_count_validation() -> None:
    rows = [DEFAULT_ROWS[0], DEFAULT_ROWS[0]]

    with pytest.raises(ProviderDataInvalid, match="Duplicate"):
        parse_hstech_constituents(factsheet_text(rows), "duplicate fixture")


def test_conflicting_declared_counts_are_rejected() -> None:
    text = factsheet_text() + "\nNo. of Constituents: 4\n"

    with pytest.raises(ProviderDataInvalid, match="count"):
        parse_hstech_constituents(text, "fixture")


def test_invalid_parser_arguments_are_rejected() -> None:
    with pytest.raises(ProviderDataInvalid):
        parse_hstech_constituents(None, "fixture")  # type: ignore[arg-type]
    with pytest.raises(ProviderDataInvalid):
        parse_hstech_constituents(factsheet_text(), " ")


def build_text_pdf(lines: Sequence[str]) -> bytes:
    """Build a tiny standards-compliant text PDF without a writer dependency."""
    operations = ["BT", "/F1 9 Tf", "50 800 Td", "12 TL"]
    for index, line in enumerate(lines):
        if index:
            operations.append("T*")
        operations.append(f"({_pdf_literal(line)}) Tj")
    operations.append("ET")
    stream = "\n".join(operations).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, pdf_object in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode("ascii"))
        content.extend(pdf_object)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(content)


def _pdf_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class FakePage:
    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error

    def extract_text(self) -> str | None:
        if self._error is not None:
            raise self._error
        return self._text


def patch_pdf(
    monkeypatch: pytest.MonkeyPatch, pages: Sequence[FakePage]
) -> tuple[Mock, Mock]:
    download = Mock(return_value=b"%PDF fixture bytes")
    reader = Mock(return_value=SimpleNamespace(pages=list(pages)))
    monkeypatch.setattr(universe_adapter, "fetch_bytes", download)
    monkeypatch.setattr(universe_adapter, "PdfReader", reader)
    return download, reader


def test_provider_downloads_bounded_pdf_reads_bytesio_and_builds_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_text = factsheet_text()
    first_page, second_page = full_text.split("9988 ", 1)
    download, reader = patch_pdf(
        monkeypatch,
        [FakePage(first_page), FakePage("9988 " + second_page)],
    )
    provider = universe_adapter.HstechUniverseProvider()

    snapshot = provider.fetch_universe("hstech")

    download.assert_called_once_with(
        universe_adapter.HSTECH_FACTSHEET_URL,
        max_bytes=universe_adapter.FACTSHEET_MAX_BYTES,
        timeout=universe_adapter.FACTSHEET_TIMEOUT_SECONDS,
        expected_content_type="application/pdf",
    )
    assert download.call_args.kwargs["max_bytes"] > 0
    assert download.call_args.kwargs["timeout"] > 0
    stream = reader.call_args.args[0]
    assert isinstance(stream, BytesIO)
    assert stream.getvalue() == b"%PDF fixture bytes"
    assert isinstance(provider, UniverseProvider)
    assert snapshot.universe_code == "hstech"
    assert snapshot.source == "hang_seng_indexes"
    assert snapshot.effective_date == date(2026, 1, 31)
    assert [item.symbol for item in snapshot.members] == [
        "0700.HK",
        "9988.HK",
        "1024.HK",
    ]
    assert len(snapshot.related_instruments) == 1
    index = snapshot.related_instruments[0]
    assert index.symbol == "HSTECH.HK"
    assert index.instrument_type == "index"
    assert index.provider_symbol == "HSTECH.HK"
    assert index not in snapshot.members


def test_provider_parses_real_pypdf_extraction_from_in_memory_official_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_content = build_text_pdf(factsheet_text(OFFICIAL_ROWS).splitlines())
    download = Mock(return_value=pdf_content)
    monkeypatch.setattr(universe_adapter, "fetch_bytes", download)

    snapshot = universe_adapter.HstechUniverseProvider().fetch_universe("hstech")

    download.assert_called_once_with(
        universe_adapter.HSTECH_FACTSHEET_URL,
        max_bytes=universe_adapter.FACTSHEET_MAX_BYTES,
        timeout=universe_adapter.FACTSHEET_TIMEOUT_SECONDS,
        expected_content_type="application/pdf",
    )
    assert pdf_content.startswith(b"%PDF-")
    assert len(snapshot.members) == len(OFFICIAL_ROWS)
    assert [item.symbol for item in snapshot.members] == [
        f"{row[0]}.HK" for row in OFFICIAL_ROWS
    ]
    assert snapshot.effective_date == date(2026, 1, 31)


def test_none_page_text_is_allowed_when_another_page_has_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_pdf(monkeypatch, [FakePage(None), FakePage(factsheet_text())])

    snapshot = universe_adapter.HstechUniverseProvider().fetch_universe("hstech")

    assert len(snapshot.members) == 3


@pytest.mark.parametrize(
    ("content", "pages"),
    [
        (b"", [FakePage(factsheet_text())]),
        (b"%PDF", []),
        (b"%PDF", [FakePage(error=ValueError("private PDF detail"))]),
        (b"%PDF", [FakePage("no constituents here")]),
        (b"%PDF", [FakePage(factsheet_text(declared_count=9))]),
    ],
    ids=["empty-download", "no-pages", "extraction-error", "empty-text", "bad-table"],
)
def test_empty_malformed_and_count_mismatched_pdfs_raise_data_invalid(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    pages: Sequence[FakePage],
) -> None:
    download, reader = patch_pdf(monkeypatch, pages)
    download.return_value = content

    with pytest.raises(ProviderDataInvalid):
        universe_adapter.HstechUniverseProvider().fetch_universe("hstech")


def test_pdf_reader_construction_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(universe_adapter, "fetch_bytes", Mock(return_value=b"%PDF"))
    monkeypatch.setattr(
        universe_adapter,
        "PdfReader",
        Mock(side_effect=ValueError("private PDF internals")),
    )

    with pytest.raises(ProviderDataInvalid) as captured:
        universe_adapter.HstechUniverseProvider().fetch_universe("hstech")
    assert "private PDF internals" not in str(captured.value)


def test_download_typed_errors_propagate_without_pdf_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        universe_adapter,
        "fetch_bytes",
        Mock(side_effect=ProviderUnavailable("offline fixture")),
    )
    reader = Mock()
    monkeypatch.setattr(universe_adapter, "PdfReader", reader)

    with pytest.raises(ProviderUnavailable, match="offline fixture"):
        universe_adapter.HstechUniverseProvider().fetch_universe("hstech")
    reader.assert_not_called()


def test_unknown_universe_fails_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = Mock()
    monkeypatch.setattr(universe_adapter, "fetch_bytes", download)

    with pytest.raises(ProviderCompatibilityError):
        universe_adapter.HstechUniverseProvider().fetch_universe("HSTECH")
    download.assert_not_called()


def test_failed_pdf_refresh_preserves_existing_repository_membership(
    monkeypatch: pytest.MonkeyPatch, session_factory: SessionFactory
) -> None:
    repository = InstrumentRepository(session_factory)
    old_member = parse_hstech_constituents(
        factsheet_text(DEFAULT_ROWS[:1]), "old snapshot"
    )[0]
    repository.replace_universe(
        UniverseSnapshot(
            universe_code="hstech",
            source="old-source",
            effective_date=date(2025, 12, 31),
            members=(old_member,),
        )
    )
    patch_pdf(monkeypatch, [FakePage(factsheet_text(declared_count=99))])

    def refresh() -> None:
        snapshot = universe_adapter.HstechUniverseProvider().fetch_universe("hstech")
        repository.replace_universe(snapshot)

    with pytest.raises(ProviderDataInvalid):
        refresh()

    assert [item.symbol for item in repository.list_members("hstech")] == ["0700.HK"]
    assert repository.get_by_symbol("hk_stock", "9988.HK") is None


def test_successful_snapshot_can_replace_members_and_upsert_related_separately(
    monkeypatch: pytest.MonkeyPatch, session_factory: SessionFactory
) -> None:
    repository = InstrumentRepository(session_factory)
    patch_pdf(monkeypatch, [FakePage(factsheet_text())])
    snapshot = universe_adapter.HstechUniverseProvider().fetch_universe("hstech")

    assert repository.replace_universe(snapshot) == (4, 3)
    assert {item.symbol for item in repository.list_members("hstech")} == {
        "0700.HK",
        "9988.HK",
        "1024.HK",
    }
    related = repository.get_by_symbol("hk_stock", "HSTECH.HK")
    assert related is not None
    assert related.instrument_type == "index"
    assert related.name == "Hang Seng TECH Index"
