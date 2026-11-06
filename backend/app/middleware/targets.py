"""Strict normalization for configured hosts and serialized web origins."""

import ipaddress
import re
from urllib.parse import urlsplit

DEFAULT_ORIGIN_PORTS = {"http": 80, "https": 443}
HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def normalize_host(value: str) -> str:
    """Return one exact host without a scheme, port, wildcard, or suffix rule."""
    candidate = value.strip().lower()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    if (
        not candidate
        or "*" in candidate
        or any(character in candidate for character in "/\\@?#")
    ):
        raise ValueError(f"Invalid allowed host: {value!r}")
    if ":" in candidate:
        try:
            return ipaddress.IPv6Address(candidate).compressed
        except ipaddress.AddressValueError as error:
            raise ValueError(f"Invalid allowed host: {value!r}") from error

    try:
        ascii_host = candidate.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError(f"Invalid allowed host: {value!r}") from error
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or any(
        HOST_LABEL.fullmatch(label) is None for label in labels
    ):
        raise ValueError(f"Invalid allowed host: {value!r}")
    return ascii_host


def normalize_origin(value: str) -> str:
    """Normalize an HTTP(S) origin and reject paths, credentials, and wildcards."""
    candidate = value.strip()
    if (
        not candidate
        or candidate.lower() == "null"
        or "*" in candidate
        or any(character.isspace() for character in candidate)
    ):
        raise ValueError("Invalid web origin")
    try:
        parsed = urlsplit(candidate)
        scheme = parsed.scheme.lower()
        if scheme not in DEFAULT_ORIGIN_PORTS or parsed.hostname is None:
            raise ValueError("Invalid web origin")
        if (
            parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Invalid web origin")
        host = normalize_host(parsed.hostname)
        port = parsed.port
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("Invalid web origin") from error

    rendered_host = f"[{host}]" if ":" in host else host
    if port is None or port == DEFAULT_ORIGIN_PORTS[scheme]:
        return f"{scheme}://{rendered_host}"
    return f"{scheme}://{rendered_host}:{port}"
