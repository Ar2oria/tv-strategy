"""Typed provider failures with bounded, sanitized public diagnostics."""

import math
import re
from numbers import Real

MAX_PROVIDER_DETAIL_LENGTH = 500
_URL_PATTERN = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
_SECRET_PATTERN = re.compile(
    r"\b(api[_-]?key|access[_-]?token|password|credential|secret)"
    r"(\s*[=:]\s*)([^\s,;]+)",
    re.IGNORECASE,
)
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
_UNSAFE_DETAIL_PATTERN = re.compile(
    r"private|token|secret|credential|password|api[_-]?key|response\s+body",
    re.IGNORECASE,
)


def normalize_retry_after(value: object) -> float | None:
    """Return only finite, nonnegative numeric wait guidance."""
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, Real)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return converted if math.isfinite(converted) and converted >= 0 else None


def sanitize_provider_detail(value: object) -> str | None:
    """Bound built-in diagnostics and remove URLs, credentials, and controls."""
    if not isinstance(value, str):
        return None
    safe_segments = tuple(
        segment
        for segment in re.split(r"[;\n]+", value)
        if not _UNSAFE_DETAIL_PATTERN.search(segment)
    )
    if not safe_segments:
        return None
    without_controls = _CONTROL_PATTERN.sub(" ", " ".join(safe_segments))
    without_urls = _URL_PATTERN.sub("[redacted URL]", without_controls)
    sanitized = _SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]",
        without_urls,
    )
    return " ".join(sanitized.split())[:MAX_PROVIDER_DETAIL_LENGTH]


class ProviderError(RuntimeError):
    """Base class for expected provider and provider-configuration failures."""

    default_message = "Market-data provider request failed"

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
        retry_after: object = None,
    ) -> None:
        super().__init__(self.default_message if message is None else message)
        self.detail = sanitize_provider_detail(detail)
        self.retry_after = normalize_retry_after(retry_after)

    @property
    def public_detail(self) -> str:
        """Return actionable detail without trusting arbitrary upstream text."""
        return self.detail or self.default_message


class ProviderUnavailable(ProviderError):
    """The upstream provider could not supply a usable response."""

    default_message = "Market-data provider is unavailable"


class ProviderRateLimited(ProviderError):
    """The upstream provider rejected a request because of rate limits."""

    default_message = "Market-data provider rate limit exceeded"


class ProviderDataInvalid(ProviderError):
    """Provider content violates the normalized market-data contract."""

    default_message = "Market-data provider returned invalid data"

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
        retry_after: object = None,
    ) -> None:
        # DataInvalid messages are built by our validators, not copied upstream.
        super().__init__(
            message,
            detail=message if detail is None else detail,
            retry_after=retry_after,
        )


class NoDataAvailable(ProviderError):
    """A caller requiring data received an empty provider result."""

    default_message = "No market data is available"


class ProviderConfigurationError(ProviderError):
    """Base class for fail-fast registry selection errors."""


class UnknownProviderError(ProviderConfigurationError):
    """No known provider or universe provider has the requested name."""

    default_message = "Unknown market-data provider"


class UnknownMarketError(ProviderConfigurationError):
    """The requested market is outside the frozen market configuration."""

    default_message = "Unknown market"


class ProviderCompatibilityError(ProviderConfigurationError):
    """A known provider cannot serve the requested market."""

    default_message = "Market-data provider is incompatible with the market"
