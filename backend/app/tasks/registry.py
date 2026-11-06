"""Validated Task registration and immutable parameter descriptors."""

import inspect
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, JsonValue, TypeAdapter

from app.tasks.base import Task

MAX_TASK_NAME_LENGTH = 256
TASK_NAME_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*"
)
_JSON_PARAMS = TypeAdapter(dict[str, JsonValue])


class TaskRegistryError(RuntimeError):
    """Base class for Task registration failures."""


class TaskRegistryConflictError(TaskRegistryError):
    """Two Task classes attempted to claim the same unique name."""


class UnknownTaskError(TaskRegistryError, KeyError):
    """A requested Task name is not registered."""


class InvalidTaskError(TaskRegistryError, TypeError):
    """A class does not satisfy the Task execution contract."""


@dataclass(frozen=True, slots=True)
class TaskDescriptor:
    """Frozen Task metadata plus factories for parameters and executions."""

    name: str
    display_name: str
    description: str
    task_class: type[Task]
    params_model: type[BaseModel]
    _params_schema: dict[str, Any]

    @property
    def params_schema(self) -> dict[str, Any]:
        return deepcopy(self._params_schema)

    @property
    def parameter_schema(self) -> dict[str, Any]:
        return self.params_schema

    def create(self) -> Task:
        return self.task_class()

    def validate_params(self, values: dict[str, Any] | None = None) -> BaseModel:
        """Validate finite JSON values and the concrete frozen parameter model."""
        normalized = _JSON_PARAMS.validate_python({} if values is None else values)
        json.dumps(normalized, allow_nan=False)
        validated = self.params_model.model_validate(normalized)
        snapshot = validated.model_dump(mode="json")
        if not isinstance(snapshot, dict):
            raise TypeError("Task parameters must serialize to a JSON object")
        json.dumps(snapshot, allow_nan=False)
        return validated


class TaskRegistry:
    """Name-indexed registry populated once during startup discovery."""

    def __init__(self) -> None:
        self._descriptors: dict[str, TaskDescriptor] = {}

    @property
    def descriptors(self) -> tuple[TaskDescriptor, ...]:
        return tuple(self._descriptors[name] for name in sorted(self._descriptors))

    def get(self, name: str) -> TaskDescriptor:
        try:
            return self._descriptors[name]
        except KeyError as error:
            available = ", ".join(sorted(self._descriptors)) or "none"
            raise UnknownTaskError(
                f"Unknown Task {name!r}; available Tasks: {available}"
            ) from error

    def register(self, task_class: type[Task]) -> type[Task]:
        descriptor = _describe(task_class)
        if descriptor.name in self._descriptors:
            raise TaskRegistryConflictError(
                f"Task name {descriptor.name!r} is already registered"
            )
        self._descriptors = {**self._descriptors, descriptor.name: descriptor}
        return task_class


def _describe(task_class: type[Task]) -> TaskDescriptor:
    _validate_class(task_class)
    try:
        schema = task_class.params_model.model_json_schema()
    except Exception as error:
        raise InvalidTaskError(
            f"Cannot build parameter JSON Schema for {task_class.__name__}: {error}"
        ) from error
    return TaskDescriptor(
        name=task_class.name,
        display_name=task_class.display_name,
        description=task_class.description,
        task_class=task_class,
        params_model=task_class.params_model,
        _params_schema=schema,
    )


def _validate_class(task_class: type[Task]) -> None:
    if not inspect.isclass(task_class) or not issubclass(task_class, Task):
        raise InvalidTaskError("Registered class must inherit Task")
    if task_class is Task or inspect.isabstract(task_class):
        raise InvalidTaskError("Registered Task must be concrete")
    if (
        not isinstance(task_class.name, str)
        or len(task_class.name) > MAX_TASK_NAME_LENGTH
        or TASK_NAME_PATTERN.fullmatch(task_class.name) is None
    ):
        raise InvalidTaskError(
            f"Task {task_class.__name__} has an invalid or blank name"
        )
    if (
        not isinstance(task_class.display_name, str)
        or not task_class.display_name.strip()
    ):
        raise InvalidTaskError(f"Task {task_class.name!r} must declare a display name")
    if not inspect.iscoroutinefunction(task_class.run):
        raise InvalidTaskError(f"Task {task_class.name!r} run must be async")
    params_model = task_class.params_model
    if not inspect.isclass(params_model) or not issubclass(params_model, BaseModel):
        raise InvalidTaskError(
            f"Task {task_class.name!r} params_model must inherit BaseModel"
        )
    if params_model.model_config.get("frozen") is not True:
        raise InvalidTaskError(f"Task {task_class.name!r} params_model must be frozen")
    if params_model.model_config.get("extra") != "forbid":
        raise InvalidTaskError(
            f"Task {task_class.name!r} params_model must set extra='forbid'"
        )


def register_task(task_class: type[Task]) -> type[Task]:
    """Register a discovered class in the process-wide startup registry."""
    default_registry.register(task_class)
    return task_class


default_registry = TaskRegistry()
