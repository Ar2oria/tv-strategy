"""Indicator registration, descriptor, and discovery behavior."""

from collections.abc import Sequence
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.dto import BarDTO
from app.indicators.base import Indicator, IndicatorContext, IndicatorParams
from app.indicators.discovery import discover_indicators
from app.indicators.models import IndicatorResult
from app.indicators.registry import (
    IndicatorRegistry,
    InvalidIndicatorError,
    RegistryConflictError,
    UnknownIndicatorError,
)


class SampleParams(IndicatorParams):
    """Representative bounded parameters used by registry tests."""

    window: int = Field(default=3, ge=2, le=20)


class SampleIndicator(Indicator):
    """Minimal concrete indicator used to inspect registration metadata."""

    name: ClassVar[str] = "test.sample"
    display_name: ClassVar[str] = "Sample indicator"
    description: ClassVar[str] = "A registry test double"
    params_model: ClassVar[type[BaseModel]] = SampleParams

    def calculate(
        self,
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        params: BaseModel,
    ) -> IndicatorResult:
        return IndicatorResult()


@pytest.fixture
def registry() -> IndicatorRegistry:
    return IndicatorRegistry()


def test_descriptor_exposes_parameter_defaults_and_bounds(
    registry: IndicatorRegistry,
) -> None:
    registry.register(SampleIndicator)

    descriptor = registry.get(SampleIndicator.name)

    assert descriptor.display_name == "Sample indicator"
    assert descriptor.description == "A registry test double"
    assert descriptor.indicator_class is SampleIndicator
    assert descriptor.params_model is SampleParams
    assert descriptor.params_schema["properties"]["window"] == {
        "default": 3,
        "maximum": 20,
        "minimum": 2,
        "title": "Window",
        "type": "integer",
    }
    assert isinstance(descriptor.create(), SampleIndicator)


def test_descriptor_is_frozen_pydantic_and_serializes_schema(
    registry: IndicatorRegistry,
) -> None:
    registry.register(SampleIndicator)
    descriptor = registry.get(SampleIndicator.name)

    assert isinstance(descriptor, BaseModel)
    assert descriptor.model_dump(mode="json")["params_schema"]["properties"][
        "window"
    ]["default"] == 3
    assert "indicator_class" not in descriptor.model_dump(mode="json")
    with pytest.raises(ValidationError):
        descriptor.display_name = "Changed"


def test_descriptor_schema_cannot_be_mutated_by_caller(
    registry: IndicatorRegistry,
) -> None:
    registry.register(SampleIndicator)
    schema = registry.get(SampleIndicator.name).params_schema
    schema["properties"]["window"]["default"] = 99

    fresh_schema = registry.get(SampleIndicator.name).params_schema

    assert fresh_schema["properties"]["window"]["default"] == 3


def test_duplicate_names_raise_conflict(registry: IndicatorRegistry) -> None:
    registry.register(SampleIndicator)

    class DuplicateIndicator(SampleIndicator):
        pass

    with pytest.raises(RegistryConflictError, match="test.sample"):
        registry.register(DuplicateIndicator)


def test_registry_register_can_be_used_as_decorator(
    registry: IndicatorRegistry,
) -> None:
    @registry.register
    class DecoratedIndicator(SampleIndicator):
        name: ClassVar[str] = "test.decorated"

    assert registry.get("test.decorated").indicator_class is DecoratedIndicator


def test_unknown_name_has_explicit_error(registry: IndicatorRegistry) -> None:
    with pytest.raises(UnknownIndicatorError, match="missing"):
        registry.get("missing")


def test_registration_rejects_non_indicator_classes(
    registry: IndicatorRegistry,
) -> None:
    with pytest.raises(InvalidIndicatorError, match="Indicator"):
        registry.register(object)  # type: ignore[arg-type]


def test_registration_rejects_mutable_parameter_models(
    registry: IndicatorRegistry,
) -> None:
    class MutableParams(BaseModel):
        value: int = 1

    class InvalidIndicator(SampleIndicator):
        name: ClassVar[str] = "test.invalid"
        params_model: ClassVar[type[BaseModel]] = MutableParams

    with pytest.raises(InvalidIndicatorError, match="frozen"):
        registry.register(InvalidIndicator)


def test_registration_rejects_frozen_params_with_extra_ignore(
    registry: IndicatorRegistry,
) -> None:
    class FrozenIgnoreParams(BaseModel):
        model_config = ConfigDict(frozen=True, extra="ignore")

        value: int = 1

    class InvalidIndicator(SampleIndicator):
        name: ClassVar[str] = "test.extra-ignore"
        params_model: ClassVar[type[BaseModel]] = FrozenIgnoreParams

    with pytest.raises(InvalidIndicatorError, match="extra.*forbid"):
        registry.register(InvalidIndicator)


def test_registration_traverses_nested_parameter_model_annotations(
    registry: IndicatorRegistry,
) -> None:
    class NestedIgnoreParams(BaseModel):
        model_config = ConfigDict(frozen=True, extra="ignore")

        value: int = 1

    class OuterParams(IndicatorParams):
        nested: tuple[NestedIgnoreParams, ...] = ()

    class InvalidIndicator(SampleIndicator):
        name: ClassVar[str] = "test.nested-extra-ignore"
        params_model: ClassVar[type[BaseModel]] = OuterParams

    with pytest.raises(
        InvalidIndicatorError,
        match="NestedIgnoreParams.*extra.*forbid",
    ):
        registry.register(InvalidIndicator)


def test_registration_rejects_non_frozen_nested_parameter_models(
    registry: IndicatorRegistry,
) -> None:
    class NestedMutableParams(BaseModel):
        model_config = ConfigDict(frozen=False, extra="forbid")

        value: int = 1

    class OuterParams(IndicatorParams):
        nested: NestedMutableParams | None = None

    class InvalidIndicator(SampleIndicator):
        name: ClassVar[str] = "test.nested-not-frozen"
        params_model: ClassVar[type[BaseModel]] = OuterParams

    with pytest.raises(InvalidIndicatorError, match="NestedMutableParams.*frozen"):
        registry.register(InvalidIndicator)


def test_input_models_are_frozen() -> None:
    params = SampleParams()
    context = IndicatorContext(symbol="TEST")

    with pytest.raises(ValidationError):
        params.window = 4
    with pytest.raises(ValidationError):
        context.symbol = "OTHER"


def test_startup_discovery_registers_built_in_indicators() -> None:
    registry = discover_indicators()

    assert registry.get("donchian").display_name == "Donchian Breakout"
    assert registry.get("rsi").display_name == "Relative Strength Index"
