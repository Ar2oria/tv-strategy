"""Bounded official-PDF provider for the current Hang Seng TECH universe."""

import logging
import re
from datetime import date, datetime
from io import BytesIO

from pypdf import PdfReader

from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.providers.errors import ProviderCompatibilityError, ProviderDataInvalid
from app.providers.http import fetch_bytes
from app.providers.hstech_parser import parse_hstech_constituents
from app.providers.timeouts import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    validate_request_timeout,
)

logger = logging.getLogger(__name__)
HSTECH_FACTSHEET_URL = (
    "https://www.hsi.com.hk/api/wsit-hsi-ddoc-ea-public-website-proxy/v1/"
    "content/gcs/download?resource=%2Fpublic-website%2Fwebapp%2Ffactsheets%2F"
    "en-hk%2Fhstech.pdf"
)
SOURCE = "hang_seng_indexes"
FACTSHEET_MAX_BYTES = 8 * 1024 * 1024
FACTSHEET_TIMEOUT_SECONDS = DEFAULT_REQUEST_TIMEOUT_SECONDS

HSTECH_INDEX = InstrumentDTO(
    symbol="HSTECH.HK",
    name="Hang Seng TECH Index",
    market="hk_stock",
    exchange="HKEX",
    currency="HKD",
    timezone="Asia/Hong_Kong",
    instrument_type="index",
    provider_symbol="HSTECH.HK",
)
_EFFECTIVE_DATE_PATTERN = re.compile(
    r"\b(?:As\s+(?:of|at)|Effective\s+Date|Data\s+as\s+of)\s*[:\-]?\s*"
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


class HstechUniverseProvider:
    """Download, extract, and validate a complete current HSTECH snapshot."""

    def __init__(
        self,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._request_timeout_seconds = validate_request_timeout(
            request_timeout_seconds
        )

    @property
    def request_timeout_seconds(self) -> float:
        return self._request_timeout_seconds

    def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
        if universe_code != "hstech":
            raise ProviderCompatibilityError(
                "Hang Seng universe provider supports hstech only"
            )
        content = fetch_bytes(
            HSTECH_FACTSHEET_URL,
            max_bytes=FACTSHEET_MAX_BYTES,
            timeout=self._request_timeout_seconds,
            expected_content_type="application/pdf",
        )
        text = _extract_pdf_text(content)
        members = parse_hstech_constituents(text, SOURCE)
        return UniverseSnapshot(
            universe_code="hstech",
            source=SOURCE,
            effective_date=_effective_date(text),
            members=tuple(members),
            related_instruments=(HSTECH_INDEX,),
        )


def _extract_pdf_text(content: bytes) -> str:
    if not content:
        raise ProviderDataInvalid("HSTECH factsheet PDF is empty")
    try:
        reader = PdfReader(BytesIO(content))
        page_texts: list[str] = []
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted is not None and not isinstance(extracted, str):
                raise TypeError("PDF page text must be a string or null")
            page_texts.append(extracted or "")
    except Exception as error:
        logger.warning(
            "HSTECH PDF extraction failed (%s)", type(error).__name__
        )
        raise ProviderDataInvalid("Could not extract HSTECH factsheet PDF") from error
    return "\n".join(page_texts)


def _effective_date(text: str) -> date | None:
    matches = list(_EFFECTIVE_DATE_PATTERN.finditer(text))
    if not matches:
        return None
    dates = {_parse_effective_date(match.group(1)) for match in matches}
    if len(dates) != 1:
        raise ProviderDataInvalid("HSTECH factsheet effective date is ambiguous")
    return next(iter(dates))


def _parse_effective_date(value: str) -> date:
    normalized = " ".join(value.split())
    for date_format in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    raise ProviderDataInvalid("HSTECH factsheet effective date is invalid")
