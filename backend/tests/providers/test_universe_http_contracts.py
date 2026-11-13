"""Official universe URLs and configured native HTTP request contracts."""

from unittest.mock import Mock

import pytest

import app.providers.invesco_universe as invesco
import app.providers.ishares_soxx as ishares
from app.providers.errors import ProviderUnavailable

@pytest.mark.parametrize(
    ("module", "provider_type", "code", "expected_content_type"),
    [
        (
            invesco,
            invesco.InvescoUniverseProvider,
            "nasdaq100",
            ("application/json", "text/plain"),
        ),
        (
            ishares,
            ishares.IsharesSoxxUniverseProvider,
            "soxx",
            ("text/csv", "text/plain"),
        ),
    ],
)
def test_universe_download_uses_configured_timeout_and_expected_content_type(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    provider_type: type,
    code: str,
    expected_content_type: str | tuple[str, ...],
) -> None:
    download = Mock(side_effect=ProviderUnavailable())
    monkeypatch.setattr(module, "fetch_bytes", download)
    provider = provider_type(request_timeout_seconds=7.25)

    with pytest.raises(ProviderUnavailable):
        provider.fetch_universe(code)

    assert download.call_args.kwargs["timeout"] == 7.25
    assert download.call_args.kwargs["expected_content_type"] == expected_content_type
