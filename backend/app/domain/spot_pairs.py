"""Domain-neutral validation for canonical uppercase crypto spot pairs."""

import re

SPOT_PAIR_PATTERN = re.compile(
    r"(?P<base>[A-Z0-9]{1,32})/(?P<quote>[A-Z0-9]{1,32})"
)
SPOT_PAIR_ERROR = "Crypto symbol must be an uppercase BASE/QUOTE spot pair"


def parse_spot_pair(value: object) -> tuple[str, str]:
    """Return base and quote for one exact spot pair, never a derivative."""
    if not isinstance(value, str):
        raise ValueError(SPOT_PAIR_ERROR)
    match = SPOT_PAIR_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(SPOT_PAIR_ERROR)
    return match.group("base"), match.group("quote")
