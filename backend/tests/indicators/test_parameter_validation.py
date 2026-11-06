"""Actual-value graph validation for validated indicator parameters."""

from collections import deque
from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import BaseModel, ConfigDict, field_serializer

from app.indicators.parameter_validation import contains_non_finite_number


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: object = None


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        complex(float("inf"), 0),
        complex(0, float("-inf")),
        complex(float("nan"), 0),
        complex(0, float("nan")),
    ],
)
def test_non_finite_numeric_values_are_detected(value: object) -> None:
    assert contains_non_finite_number(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        1,
        -1,
        1.5,
        complex(1.5, -2.5),
        Decimal("1.25"),
        Fraction(1, 3),
        deque([1, 2]),
        "inf",
    ],
)
def test_finite_and_non_numeric_values_are_accepted(value: object) -> None:
    assert not contains_non_finite_number(value)


@pytest.mark.parametrize(
    "value",
    [
        Params(value=float("inf")),
        {"nested": [float("inf")]},
        (float("nan"),),
        {float("-inf")},
        frozenset({Decimal("Infinity")}),
        deque([float("inf")]),
        {"value": float("inf")}.values(),
        Params(value=Params(value=Decimal("NaN"))),
        {float("inf"): "non-finite mapping key"},
    ],
    ids=[
        "model-field",
        "mapping-and-list",
        "tuple",
        "set",
        "frozen-set",
        "deque",
        "dict-values",
        "nested-model",
        "mapping-key",
    ],
)
def test_nested_actual_values_are_detected_without_serialization(
    value: object,
) -> None:
    assert contains_non_finite_number(value)


def test_cycles_terminate_and_do_not_hide_later_invalid_values() -> None:
    cyclic_list: list[object] = []
    cyclic_list.append(cyclic_list)
    assert not contains_non_finite_number(cyclic_list)

    cyclic_mapping: dict[str, object] = {}
    cyclic_mapping["self"] = cyclic_mapping
    cyclic_mapping["invalid"] = Decimal("Infinity")
    assert contains_non_finite_number(cyclic_mapping)

    cyclic_deque: deque[object] = deque()
    cyclic_deque.append(cyclic_deque)
    assert not contains_non_finite_number(cyclic_deque)
    cyclic_deque.append(complex(float("inf"), 0))
    assert contains_non_finite_number(cyclic_deque)


def test_unsupported_iterables_fail_closed_without_being_consumed() -> None:
    consumed: list[str] = []

    def one_shot_values() -> Iterator[object]:
        consumed.append("consumed")
        yield float("inf")

    generator = one_shot_values()
    assert contains_non_finite_number(generator)
    assert contains_non_finite_number([generator])
    assert consumed == []

    class UnknownIterable:
        def __iter__(self) -> Iterator[object]:
            raise AssertionError("unknown iterable must not be iterated")

    assert contains_non_finite_number(UnknownIterable())


def test_ordinary_non_iterable_scalar_objects_remain_supported() -> None:
    class Scalar:
        pass

    assert not contains_non_finite_number(Scalar())


def test_inspection_never_invokes_an_arbitrary_field_serializer() -> None:
    class ExplodingSerializerParams(Params):
        @field_serializer("value")
        def fail_if_called(self, value: object) -> object:
            raise AssertionError("serializer must not be invoked")

    params = ExplodingSerializerParams(value=float("inf"))

    assert contains_non_finite_number(params)
