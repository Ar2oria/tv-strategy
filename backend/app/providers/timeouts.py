"""Validation for snapshotted provider request timeouts."""

import math
from numbers import Real

DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0


def validate_request_timeout(value: object) -> float:
    """Return a positive finite timeout without accepting booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("request_timeout_seconds must be a positive finite number")
    return float(value)
