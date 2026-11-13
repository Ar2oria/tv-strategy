"""Bounded synchronous HTTP downloads with every upstream call mocked."""

import logging
from collections.abc import Iterator
from unittest.mock import MagicMock, Mock

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


class ChunkedStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks


def test_fetch_bytes_returns_content_at_the_exact_limit_and_applies_timeout() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(URL).mock(
            return_value=httpx.Response(
                200,
                stream=ChunkedStream((b"ab", b"cd")),
            )
        )

        content = fetch_bytes(URL, max_bytes=4, timeout=1.25)

    assert content == b"abcd"
    assert route.called
    request = route.calls.last.request
    assert request.method == "GET"
    assert set(request.extensions["timeout"].values()) == {1.25}


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (429, ProviderRateLimited),
        (500, ProviderUnavailable),
        (404, ProviderUnavailable),
    ],
)
def test_http_statuses_map_to_typed_provider_errors(
    status: int,
    error_type: type[Exception],
) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(status, content=b"private upstream response")

        with pytest.raises(error_type) as captured:
            fetch_bytes(URL, max_bytes=100, timeout=1.0)

    assert "private upstream response" not in str(captured.value)
    assert URL not in str(captured.value)


def test_declared_content_length_over_the_limit_is_rejected_before_streaming() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(
            200,
            headers={"Content-Length": "101"},
            content=b"small",
        )

        with pytest.raises(ProviderDataInvalid, match="size"):
            fetch_bytes(URL, max_bytes=100, timeout=1.0)


@pytest.mark.parametrize("declared_length", [None, "4"])
def test_actual_streamed_bytes_over_the_limit_are_rejected(
    declared_length: str | None,
) -> None:
    headers = {} if declared_length is None else {"Content-Length": declared_length}
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).mock(
            return_value=httpx.Response(
                200,
                headers=headers,
                stream=ChunkedStream((b"abc", b"def")),
            )
        )

        with pytest.raises(ProviderDataInvalid, match="size"):
            fetch_bytes(URL, max_bytes=4, timeout=1.0)


@pytest.mark.parametrize("declared_length", ["not-a-number", "-1", "1, 1"])
def test_malformed_content_length_is_rejected(declared_length: str) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(
            200,
            headers={"Content-Length": declared_length},
            content=b"x",
        )

        with pytest.raises(ProviderDataInvalid, match="Content-Length"):
            fetch_bytes(URL, max_bytes=10, timeout=1.0)


def test_timeout_maps_to_sanitized_error_and_logs_exception_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).mock(
            side_effect=httpx.ReadTimeout("private timeout detail with credential")
        )

        with caplog.at_level(logging.WARNING, logger="app.providers.http"):
            with pytest.raises(ProviderUnavailable, match="timed out") as captured:
                fetch_bytes(URL, max_bytes=10, timeout=0.5)

    assert "private timeout detail" not in str(captured.value)
    assert "credential" not in str(captured.value)
    assert "timed out" in (captured.value.detail or "")
    assert "ReadTimeout" in caplog.text
    assert "private timeout detail" not in caplog.text


def test_transport_failure_and_credentials_never_reach_public_error() -> None:
    credential_url = "https://user:secret@example.test/data?api_key=supersecret"
    with respx.mock(assert_all_called=True) as mock:
        mock.route(method="GET", host="example.test", path="/data").mock(
            side_effect=httpx.ConnectError("failed with supersecret")
        )

        with pytest.raises(ProviderUnavailable) as captured:
            fetch_bytes(credential_url, max_bytes=10, timeout=1.0)

    public_message = str(captured.value)
    assert "secret" not in public_message
    assert "supersecret" not in public_message
    assert "example.test" not in public_message


@pytest.mark.parametrize("max_bytes", [0, -1, 1.5, True])
def test_invalid_byte_limit_fails_before_any_request(max_bytes: object) -> None:
    with respx.mock(assert_all_called=False):
        with pytest.raises(ValueError):
            fetch_bytes(URL, max_bytes=max_bytes, timeout=1.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_timeout_fails_before_any_request(timeout: object) -> None:
    with respx.mock(assert_all_called=False):
        with pytest.raises(ValueError):
            fetch_bytes(URL, max_bytes=1, timeout=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("url", ["", "ftp://example.test/data", "https://"])
def test_invalid_url_fails_without_leaking_it(url: str) -> None:
    with respx.mock(assert_all_called=False):
        with pytest.raises(ValueError) as captured:
            fetch_bytes(url, max_bytes=1, timeout=1.0)

    assert str(captured.value) == "Invalid provider URL"


def test_verified_text_plain_is_accepted_alongside_the_primary_media_type() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(
            200,
            headers={"Content-Type": "text/plain; charset=UTF-8"},
            content=b'{"holdings": []}',
        )

        content = fetch_bytes(
            URL,
            max_bytes=100,
            timeout=1.0,
            expected_content_type=("application/json", "text/plain"),
        )

    assert content == b'{"holdings": []}'


def test_unlisted_html_is_rejected_even_when_json_is_allowed() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(URL).respond(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html>not provider data</html>",
        )

        with pytest.raises(ProviderDataInvalid, match="Content-Type"):
            fetch_bytes(
                URL,
                max_bytes=100,
                timeout=1.0,
                expected_content_type=("application/json", "text/plain"),
            )


@pytest.mark.parametrize(
    "expected",
    [(), ("application/json", ""), ("application/json", 1)],
    ids=["empty-allowlist", "blank-entry", "non-string-entry"],
)
def test_invalid_media_type_allowlists_fail_before_any_request(
    expected: tuple[object, ...],
) -> None:
    with respx.mock(assert_all_called=False):
        with pytest.raises(ValueError):
            fetch_bytes(
                URL,
                max_bytes=100,
                timeout=1.0,
                expected_content_type=expected,  # type: ignore[arg-type]
            )


@pytest.mark.parametrize("proxy_url", [None, "socks5h://127.0.0.1:1080"])
def test_http_client_uses_only_the_market_proxy(
    monkeypatch: pytest.MonkeyPatch, proxy_url: str | None
) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    stream = MagicMock()
    stream.__enter__.return_value = httpx.Response(200, content=b"ok")
    client.stream.return_value = stream
    constructor = Mock(return_value=client)
    monkeypatch.setattr("app.providers.http.httpx.Client", constructor)

    assert fetch_bytes(URL, max_bytes=10, timeout=2.0, proxy_url=proxy_url) == b"ok"

    constructor.assert_called_once_with(
        timeout=2.0,
        follow_redirects=False,
        proxy=proxy_url,
        trust_env=False,
    )
