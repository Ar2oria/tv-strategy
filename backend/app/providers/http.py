"""Small synchronous HTTP helper for bounded untrusted provider downloads."""

import logging
import math
from numbers import Real

import httpx

from app.providers.errors import (
    ProviderDataInvalid,
    ProviderRateLimited,
    ProviderUnavailable,
    normalize_retry_after,
)

logger = logging.getLogger(__name__)
RATE_LIMIT_STATUSES = frozenset({418, 429})


def fetch_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    expected_content_type: str | None = None,
) -> bytes:
    """GET at most max_bytes without trusting upstream metadata or content."""
    _validate_arguments(url, max_bytes, timeout, expected_content_type)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                _require_success_status(response)
                _validate_content_type(response, expected_content_type)
                _validate_declared_size(response, max_bytes)
                return _read_bounded(response, max_bytes)
    except httpx.TimeoutException as error:
        logger.warning("Provider request timed out (%s)", type(error).__name__)
        raise ProviderUnavailable(
            "Market-data provider request timed out",
            detail="Market-data provider request timed out",
        ) from None
    except httpx.InvalidURL:
        raise ValueError("Invalid provider URL") from None
    except (httpx.HTTPError, httpx.StreamError) as error:
        logger.warning("Provider HTTP failure (%s)", type(error).__name__)
        raise ProviderUnavailable() from None


def _validate_arguments(
    url: str,
    max_bytes: int,
    timeout: float,
    expected_content_type: str | None,
) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, Real)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout must be a positive finite number")
    if not isinstance(url, str) or not url:
        raise ValueError("Invalid provider URL")
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError, ValueError):
        raise ValueError("Invalid provider URL") from None
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ValueError("Invalid provider URL")
    if expected_content_type is not None:
        if (
            not isinstance(expected_content_type, str)
            or expected_content_type != expected_content_type.strip().lower()
            or "/" not in expected_content_type
            or ";" in expected_content_type
        ):
            raise ValueError("expected_content_type must be a lowercase media type")


def _require_success_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    logger.warning("Provider returned HTTP status %s", response.status_code)
    if response.status_code in RATE_LIMIT_STATUSES:
        retry_after = normalize_retry_after(response.headers.get("retry-after"))
        raise ProviderRateLimited(retry_after=retry_after)
    raise ProviderUnavailable()


def _validate_content_type(
    response: httpx.Response,
    expected_content_type: str | None,
) -> None:
    if expected_content_type is None:
        return
    header = response.headers.get("content-type")
    if header is None or not header.strip():
        return
    actual = header.partition(";")[0].strip().casefold()
    if actual != expected_content_type:
        raise ProviderDataInvalid("Provider response has unexpected Content-Type")


def _validate_declared_size(response: httpx.Response, max_bytes: int) -> None:
    declared = response.headers.get("content-length")
    if declared is None:
        return
    try:
        size = int(declared, 10)
    except (TypeError, ValueError):
        raise ProviderDataInvalid("Invalid provider Content-Length") from None
    if size < 0:
        raise ProviderDataInvalid("Invalid provider Content-Length")
    if size > max_bytes:
        raise ProviderDataInvalid("Provider response exceeds the allowed size")


def _read_bounded(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ProviderDataInvalid("Provider response exceeds the allowed size")
        chunks.append(chunk)
    return b"".join(chunks)
