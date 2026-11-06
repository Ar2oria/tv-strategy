"""Structured upstream retry guidance without parsing arbitrary error text."""

from app.providers.errors import normalize_retry_after


def retry_after_from_error(error: Exception) -> float | None:
    """Read numeric guidance only from SDK attributes or response headers."""
    direct = normalize_retry_after(getattr(error, "retry_after", None))
    if direct is not None:
        return direct
    containers = (error, getattr(error, "response", None))
    for container in containers:
        if container is None:
            continue
        headers = getattr(container, "headers", None)
        value = _header_value(headers, "retry-after")
        guidance = normalize_retry_after(value)
        if guidance is not None:
            return guidance
    return None


def _header_value(headers: object, name: str) -> object:
    if headers is None:
        return None
    try:
        items = headers.items()  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        return None
    try:
        for key, value in items:
            if isinstance(key, str) and key.casefold() == name:
                return value
    except (RuntimeError, TypeError, ValueError):
        return None
    return None
