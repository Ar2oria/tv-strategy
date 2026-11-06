"""Official universe URLs and configured native HTTP request contracts."""

from unittest.mock import Mock

import pytest

import app.providers.hstech_universe as hstech
import app.providers.invesco_universe as invesco
import app.providers.ishares_soxx as ishares
from app.providers.errors import ProviderUnavailable

VERIFIED_HSTECH_URL = (
    "https://www.hsi.com.hk/api/wsit-hsi-ddoc-ea-public-website-proxy/v1/"
    "content/gcs/download?resource=%2Fpublic-website%2Fwebapp%2Ffactsheets%2F"
    "en-hk%2Fhstech.pdf"
)


def test_hstech_uses_controller_verified_official_pdf_url() -> None:
    assert hstech.HSTECH_FACTSHEET_URL == VERIFIED_HSTECH_URL


@pytest.mark.parametrize(
    ("module", "provider_type", "code", "expected_content_type"),
    [
        (hstech, hstech.HstechUniverseProvider, "hstech", "application/pdf"),
        (
            invesco,
            invesco.InvescoUniverseProvider,
            "nasdaq100",
            "application/json",
        ),
        (
            ishares,
            ishares.IsharesSoxxUniverseProvider,
            "soxx",
            "text/csv",
        ),
    ],
)
def test_universe_download_uses_configured_timeout_and_expected_content_type(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    provider_type: type,
    code: str,
    expected_content_type: str,
) -> None:
    download = Mock(side_effect=ProviderUnavailable())
    monkeypatch.setattr(module, "fetch_bytes", download)
    provider = provider_type(request_timeout_seconds=7.25)

    with pytest.raises(ProviderUnavailable):
        provider.fetch_universe(code)

    assert download.call_args.kwargs["timeout"] == 7.25
    assert download.call_args.kwargs["expected_content_type"] == expected_content_type
