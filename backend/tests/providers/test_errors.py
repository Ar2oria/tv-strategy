"""Public provider-detail sanitization contracts."""

import pytest

from app.providers.errors import sanitize_provider_detail


@pytest.mark.parametrize(
    "url",
    [
        "http://proxy.example:8080",
        "https://proxy.example:8443",
        "socks5://proxy.example:1080",
        "socks5h://proxy.example:1080",
    ],
)
def test_proxy_urls_are_redacted_from_public_details(url: str) -> None:
    detail = sanitize_provider_detail(f"request failed via {url}/path")

    assert detail is not None
    assert url not in detail
    assert "[redacted URL]" in detail
