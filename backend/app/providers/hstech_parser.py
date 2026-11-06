"""Strict parser for the current HSTECH official factsheet constituent table."""

import re
from dataclasses import dataclass

from app.domain.dto import InstrumentDTO
from app.providers.errors import ProviderDataInvalid

_COUNT_PATTERN = re.compile(
    r"^[ \t]*(?:(?:Number|No\.?)\s+of\s+Constituents|"
    r"(?:Total\s+)?Constituents[ \t]*:)[ \t]*:?[ \t]*"
    r"(?P<value>.*?)[ \t]*$",
    re.IGNORECASE,
)
_ROW_START = re.compile(r"^\d{4}\s+")
_HEADER_SEARCH_LINES = 8
_INDUSTRIES = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Consumer Services",
    "Consumer Goods",
    "Commerce & Industry",
    "Properties & Construction",
    "Information Technology",
    "Health Care",
    "Healthcare",
    "Real Estate",
    "Telecommunications",
    "Industrials",
    "Financials",
    "Materials",
    "Utilities",
    "Energy",
)
_SHARE_TYPES = (
    "Other HK-listed Mainland Companies",
    "Other HK-listed Mainland Company",
    "Other HK-listed Mainland Co.",
    "Ordinary Shares",
    "Ordinary Share",
    "H Shares",
    "H Share",
    "Red Chips",
    "Red Chip",
    "P Chips",
    "P Chip",
)
_ROW_PATTERN = re.compile(
    r"^(?P<code>\d{4})\s+(?P<name>.+?)\s+"
    r"(?P<industry>"
    + "|".join(re.escape(value) for value in sorted(_INDUSTRIES, key=len, reverse=True))
    + r")\s+(?P<share_type>"
    + "|".join(re.escape(value) for value in sorted(_SHARE_TYPES, key=len, reverse=True))
    + r")(?:\s+(?:\d{1,3}(?:\.\d+)?|[-–—])\s*%?)?$",
    re.IGNORECASE,
)
_ROW_WITH_ISIN_PATTERN = re.compile(
    r"^(?P<code>\d{4})\s+(?P<isin>[A-Z0-9]{12})\s+(?P<name>.+?)\s+"
    r"(?P<industry>"
    + "|".join(re.escape(value) for value in sorted(_INDUSTRIES, key=len, reverse=True))
    + r")\s+(?P<share_type>"
    + "|".join(re.escape(value) for value in sorted(_SHARE_TYPES, key=len, reverse=True))
    + r")(?:\s+(?:\d{1,3}(?:\.\d+)?|[-–—])\s*%?)?$",
    re.IGNORECASE,
)
_FOOTER_PATTERN = re.compile(
    r"^(?:Disclaimer\b|Source\s*:|Notes?\s*:|Copyright\b|"
    r"Total\s+\d{1,3}(?:\.\d+)?\s*%?$|"
    r"All rights reserved\b|www\.hsi\.com\.hk\b|"
    r"Hang Seng Indexes Company\b|For (?:more|further) information\b|"
    r"Contact Us\b|INDEX PERFORMANCE\b|INDEX FUNDAMENTALS\b)",
    re.IGNORECASE,
)
_HEADER_RESIDUE = re.compile(
    r"^(?:Weighting\b|Stock Code\b|Code\b|Company(?: Name)?\b|"
    r"Industry\b|Share\s*Type\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ConstituentTable:
    lines: tuple[str, ...]
    has_isin: bool


def parse_hstech_constituents(text: str, source: str) -> list[InstrumentDTO]:
    """Parse every unique row and reconcile it with the factsheet's declaration."""
    if not isinstance(source, str) or not source.strip():
        raise ProviderDataInvalid("HSTECH parser source must be a non-empty string")
    source_name = source.strip()
    if not isinstance(text, str) or not text.strip():
        raise _invalid(source_name, "Factsheet text is empty")

    normalized_text = text.replace(" ", " ").replace(" ", " ")
    declared_count = _declared_count(normalized_text, source_name)
    table_lines = _table_lines(normalized_text.splitlines(), source_name)
    row_texts = _row_texts(table_lines.lines, source_name)
    if not row_texts:
        raise _invalid(source_name, "Constituent table has no rows")

    members: list[InstrumentDTO] = []
    seen_codes: set[str] = set()
    for row_text in row_texts:
        member = _parse_row(
            row_text,
            source_name,
            has_isin=table_lines.has_isin,
        )
        if member.provider_symbol in seen_codes:
            raise _invalid(
                source_name,
                f"Duplicate HSTECH constituent code {member.provider_symbol}",
            )
        seen_codes.add(member.provider_symbol)
        members.append(member)

    if len(members) != declared_count:
        raise _invalid(
            source_name,
            f"Declared constituent count {declared_count} does not match "
            f"actual unique rows {len(members)}",
        )
    return members


def _declared_count(text: str, source: str) -> int:
    declarations = [
        match
        for line in text.splitlines()
        if (match := _COUNT_PATTERN.fullmatch(line)) is not None
    ]
    if not declarations:
        raise _invalid(source, "Missing declared constituent count")
    counts = [_positive_count(match.group("value"), source) for match in declarations]
    if len(set(counts)) != 1:
        raise _invalid(source, "Conflicting declared constituent counts")
    return counts[0]


def _positive_count(value: str, source: str) -> int:
    if re.fullmatch(r"\d+", value) is None:
        raise _invalid(
            source,
            "Invalid declared constituent count; expected a positive integer",
        )
    try:
        count = int(value)
    except ValueError:
        raise _invalid(source, "Declared constituent count is too large") from None
    if count <= 0:
        raise _invalid(source, "Declared constituent count must be positive")
    return count


def _table_lines(lines: list[str], source: str) -> ConstituentTable:
    cleaned = [_clean(line) for line in lines]
    for start, line in enumerate(cleaned):
        if "constituents" not in line.casefold():
            continue
        last = min(len(cleaned), start + _HEADER_SEARCH_LINES)
        for end in range(start, last):
            header = " ".join(cleaned[start : end + 1])
            if _is_table_header(header):
                return ConstituentTable(
                    lines=tuple(cleaned[end + 1 :]),
                    has_isin=bool(
                        re.search(r"\bISIN\s+CODE\b", header, re.IGNORECASE)
                    ),
                )
    raise _invalid(source, "Missing CONSTITUENTS table or required header")


def _is_table_header(header: str) -> bool:
    return all(
        (
            re.search(r"\bCONSTITUENTS\b", header, re.IGNORECASE),
            re.search(r"\b(?:Stock\s+)?Code\b", header, re.IGNORECASE),
            re.search(r"\bCompany(?:\s+Name)?\b", header, re.IGNORECASE),
            re.search(r"\bIndustry\b", header, re.IGNORECASE),
            re.search(r"\bShare\s*Type\b", header, re.IGNORECASE),
        )
    )


def _row_texts(lines: tuple[str, ...], source: str) -> list[str]:
    rows: list[str] = []
    current: list[str] = []
    for index, line in enumerate(lines):
        if not line:
            continue
        if _FOOTER_PATTERN.match(line):
            break
        if _COUNT_PATTERN.search(line):
            _finish_row(rows, current)
            current = []
            continue
        if _HEADER_RESIDUE.match(line):
            _finish_row(rows, current)
            current = []
            continue
        if _ROW_START.match(line):
            _finish_row(rows, current)
            current = [line]
            continue
        if current:
            current.append(line)
            continue
        raise _invalid(source, f"Invalid HSTECH constituent row at index {index}")
    _finish_row(rows, current)
    return rows


def _finish_row(rows: list[str], current: list[str]) -> None:
    if current:
        rows.append(_clean(" ".join(current)))


def _parse_row(
    row_text: str,
    source: str,
    *,
    has_isin: bool = False,
) -> InstrumentDTO:
    pattern = _ROW_WITH_ISIN_PATTERN if has_isin else _ROW_PATTERN
    match = pattern.fullmatch(row_text)
    if match is None:
        raise _invalid(
            source,
            "Invalid constituent row; verify four-digit code, company name, "
            "industry, and share type boundaries",
        )
    code = match.group("code")
    name = _clean(match.group("name"))
    if not name:
        raise _invalid(source, "Constituent company name is empty")
    return InstrumentDTO(
        symbol=f"{code}.HK",
        name=name,
        market="hk_stock",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        instrument_type="stock",
        provider_symbol=f"{code}.HK",
    )


def _clean(value: str) -> str:
    return " ".join(value.split())


def _invalid(source: str, message: str) -> ProviderDataInvalid:
    return ProviderDataInvalid(f"{source}: {message}")
