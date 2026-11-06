"""Retry guidance, response media types, and safe provider diagnostics."""

import httpx
import pytest
import respx

from app.providers.errors import (
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.http import fetch_bytes

URL = "https://example.test/data"


@pytest.mark.parametrize("status", [418, 429])
def test_rate_limit_response_preserves_numeric_retry_after(status: int) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(
            status,
            headers={"Retry-After": "45.5"},
            content=b"private response body",
        )

        with pytest.raises(ProviderRateLimited) as captured:
            fetch_bytes(URL, max_bytes=100, timeout=1.0)

    assert captured.value.retry_after == 45.5
    assert "private response body" not in str(captured.value)
    assert "45.5" not in str(captured.value)


@pytest.mark.parametrize(
    "guidance",
    ["", "not-a-number", "-1", "nan", "inf", "Wed, 21 Oct 2026 07:28:00 GMT"],
)
def test_invalid_retry_after_is_ignored(guidance: str) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(429, headers={"Retry-After": guidance})

        with pytest.raises(ProviderRateLimited) as captured:
            fetch_bytes(URL, max_bytes=100, timeout=1.0)

    assert captured.value.retry_after is None


def test_non_rate_limit_failure_does_not_invent_retry_guidance() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(503, headers={"Retry-After": "90"})

        with pytest.raises(ProviderUnavailable) as captured:
            fetch_bytes(URL, max_bytes=100, timeout=1.0)

    assert captured.value.retry_after is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "application/pdf"),
        ("application/pdf", "application/pdf"),
        ("application/pdf; charset=binary", "application/pdf"),
        ("Application/JSON; Charset=UTF-8", "application/json"),
    ],
)
def test_expected_content_type_accepts_missing_or_compatible_header(
    header: str | None,
    expected: str,
) -> None:
    headers = {} if header is None else {"Content-Type": header}
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(200, headers=headers, content=b"payload")

        assert fetch_bytes(
            URL,
            max_bytes=100,
            timeout=1.0,
            expected_content_type=expected,
        ) == b"payload"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("text/html", "application/pdf"),
        ("application/json", "text/csv"),
        ("text/csv", "application/json"),
    ],
)
def test_conflicting_content_type_is_rejected(header: str, expected: str) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(
            200,
            headers={"Content-Type": header},
            content=b"not the promised media type",
        )

        with pytest.raises(ProviderDataInvalid, match="Content-Type") as captured:
            fetch_bytes(
                URL,
                max_bytes=100,
                timeout=1.0,
                expected_content_type=expected,
            )

    assert "not the promised media type" not in str(captured.value)


def test_data_invalid_preserves_actionable_bounded_sanitized_detail() -> None:
    error = ProviderDataInvalid(
        "Missing OHLCV columns; see "
        "https://user:secret@example.test/path?api_key=supersecret"
    )

    assert error.detail is not None
    assert "Missing OHLCV columns" in error.detail
    assert "example.test" not in error.detail
    assert "secret" not in error.detail
    assert "supersecret" not in error.detail
    assert len(ProviderDataInvalid("x" * 2_000).detail or "") <= 500


def test_raw_token_like_text_is_not_promoted_to_public_detail() -> None:
    error = ProviderDataInvalid("private-token-and-upstream-url")

    assert error.detail is None
    assert error.public_detail == error.default_message
    assert "private-token" not in error.public_detail


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "bad"])
def test_provider_error_normalizes_invalid_retry_after(value: object) -> None:
    assert ProviderRateLimited(retry_after=value).retry_after is None  # type: ignore[arg-type]
