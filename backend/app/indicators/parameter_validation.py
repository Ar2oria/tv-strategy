"""Finite-number checks over actual validated parameter values."""

import math
from collections.abc import Collection, Iterable, Iterator, Mapping
from decimal import Decimal
from itertools import chain
from numbers import Rational, Real

from pydantic import BaseModel


def contains_non_finite_number(
    value: object,
    ancestors: frozenset[int] = frozenset(),
) -> bool:
    """Inspect a value graph without invoking Pydantic serializers.

    Only ancestor identities are retained, which terminates cycles while still
    inspecting shared objects reached through another branch. Finite integral
    and rational values never need lossy conversion to a float. Unsupported
    iterables fail closed without being iterated or consumed.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, complex):
        return not (
            math.isfinite(value.real) and math.isfinite(value.imag)
        )
    if isinstance(value, Decimal):
        return not value.is_finite()
    if isinstance(value, Real):
        if isinstance(value, Rational):
            return False
        return not math.isfinite(value)
    if isinstance(value, (str, bytes, bytearray)):
        return False
    if isinstance(value, Iterator):
        return True
    if not _is_container(value):
        return isinstance(value, Iterable)

    identity = id(value)
    if identity in ancestors:
        return False
    nested_ancestors = ancestors | {identity}
    return any(
        contains_non_finite_number(child, nested_ancestors)
        for child in _child_values(value)
    )


def _is_container(value: object) -> bool:
    if isinstance(value, (str, bytes, bytearray)):
        return False
    return isinstance(value, (BaseModel, Collection))


def _child_values(value: object) -> Iterable[object]:
    """Read stored model fields and finite container entries directly."""
    if isinstance(value, BaseModel):
        return value.__dict__.values()
    if isinstance(value, Mapping):
        return chain(value.keys(), value.values())
    if isinstance(value, Collection) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return value
    return ()
