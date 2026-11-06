"""Validated indicator registration and immutable descriptors."""

import inspect
import re
from collections.abc import Iterator
from copy import deepcopy
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, computed_field

from app.indicators.base import Indicator
from app.indicators.models import IDENTIFIER_PATTERN


class RegistryError(RuntimeError):
    """Base class for indicator registry failures."""


class RegistryConflictError(RegistryError):
    """Two indicator classes attempted to claim the same public name."""


class UnknownIndicatorError(RegistryError, KeyError):
    """A caller requested an indicator name that is not registered."""


class InvalidIndicatorError(RegistryError, TypeError):
    """A class does not satisfy the indicator protocol."""


class IndicatorDescriptor(BaseModel):
    """Frozen metadata plus factories for one registered indicator class."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    name: str
    display_name: str
    description: str
    indicator_class: type[Indicator] = Field(exclude=True)
    params_model: type[BaseModel] = Field(exclude=True)
    _params_schema: dict[str, Any] = PrivateAttr(default_factory=dict)

    def __init__(self, *, params_schema: dict[str, Any], **data: Any) -> None:
        super().__init__(**data)
        object.__setattr__(self, "_params_schema", deepcopy(params_schema))

    @computed_field
    @property
    def params_schema(self) -> dict[str, Any]:
        """Return a defensive JSON Schema copy that callers may safely modify."""
        return deepcopy(self._params_schema)

    @property
    def parameter_schema(self) -> dict[str, Any]:
        """Compatibility alias using the long-form parameter name."""
        return self.params_schema

    def create(self) -> Indicator:
        """Create independent indicator state for one calculation."""
        return self.indicator_class()


class IndicatorRegistry:
    """Name-indexed registry populated during startup module discovery."""

    def __init__(self) -> None:
        self._descriptors: dict[str, IndicatorDescriptor] = {}

    @property
    def descriptors(self) -> tuple[IndicatorDescriptor, ...]:
        return tuple(self._descriptors[name] for name in sorted(self._descriptors))

    def get(self, name: str) -> IndicatorDescriptor:
        try:
            return self._descriptors[name]
        except KeyError as error:
            available = ", ".join(sorted(self._descriptors)) or "none"
            raise UnknownIndicatorError(
                f"Unknown indicator {name!r}; available indicators: {available}"
            ) from error

    def register(self, indicator_class: type[Indicator]) -> type[Indicator]:
        """Validate and register a class; also usable as a class decorator."""
        descriptor = self._describe(indicator_class)
        if descriptor.name in self._descriptors:
            raise RegistryConflictError(
                f"Indicator name {descriptor.name!r} is already registered"
            )
        self._descriptors = {**self._descriptors, descriptor.name: descriptor}
        return indicator_class

    @staticmethod
    def _describe(indicator_class: type[Indicator]) -> IndicatorDescriptor:
        _validate_class(indicator_class)
        params_model = indicator_class.params_model
        try:
            schema = params_model.model_json_schema()
        except Exception as error:
            raise InvalidIndicatorError(
                f"Cannot build parameter JSON Schema for {indicator_class.__name__}: "
                f"{error}"
            ) from error
        return IndicatorDescriptor(
            name=indicator_class.name,
            display_name=indicator_class.display_name,
            description=indicator_class.description,
            indicator_class=indicator_class,
            params_model=params_model,
            params_schema=schema,
        )


def _validate_class(indicator_class: type[Indicator]) -> None:
    if not inspect.isclass(indicator_class) or not issubclass(indicator_class, Indicator):
        raise InvalidIndicatorError("Registered class must inherit Indicator")
    if indicator_class is Indicator or inspect.isabstract(indicator_class):
        raise InvalidIndicatorError("Registered indicator must be concrete")
    if not re.fullmatch(IDENTIFIER_PATTERN, indicator_class.name):
        raise InvalidIndicatorError(
            f"Indicator {indicator_class.__name__} has invalid or blank name"
        )
    if not indicator_class.display_name.strip():
        raise InvalidIndicatorError(
            f"Indicator {indicator_class.name!r} must declare a display name"
        )
    params_model = indicator_class.params_model
    if not inspect.isclass(params_model) or not issubclass(params_model, BaseModel):
        raise InvalidIndicatorError(
            f"Indicator {indicator_class.name!r} params_model must inherit BaseModel"
        )
    _validate_parameter_model(indicator_class.name, params_model)


def _nested_parameter_models(annotation: Any) -> Iterator[type[BaseModel]]:
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for argument in get_args(annotation):
        yield from _nested_parameter_models(argument)


def _validate_parameter_model(
    indicator_name: str,
    params_model: type[BaseModel],
    checked: frozenset[type[BaseModel]] = frozenset(),
) -> None:
    if params_model in checked:
        return
    if params_model.model_config.get("frozen") is not True:
        raise InvalidIndicatorError(
            f"Indicator {indicator_name!r} parameter model "
            f"{params_model.__name__} must be frozen"
        )
    if params_model.model_config.get("extra") != "forbid":
        raise InvalidIndicatorError(
            f"Indicator {indicator_name!r} parameter model "
            f"{params_model.__name__} must set extra='forbid'"
        )
    nested_checked = checked | {params_model}
    for field in params_model.model_fields.values():
        for nested in _nested_parameter_models(field.annotation):
            _validate_parameter_model(indicator_name, nested, nested_checked)


def register_indicator(indicator_class: type[Indicator]) -> type[Indicator]:
    """Register a discovered class in the process-wide startup registry."""
    default_registry.register(indicator_class)
    return indicator_class


default_registry = IndicatorRegistry()
