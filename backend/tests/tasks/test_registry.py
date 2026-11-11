"""Task registration, validation, and restart discovery contracts."""

from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.tasks.base import Task, TaskParams, TaskResult
from app.tasks.builtin.purge_history import PurgeHistoryTask
from app.tasks.discovery import discover_tasks
from app.tasks.registry import (
    InvalidTaskError,
    TaskRegistry,
    TaskRegistryConflictError,
)


class WindowParams(TaskParams):
    window: int = 7


class ExampleTask(Task):
    name: ClassVar[str] = "test.example"
    display_name: ClassVar[str] = "Example"
    description: ClassVar[str] = "Example task"
    params_model: ClassVar[type[BaseModel]] = WindowParams

    async def run(self, context: object, params: BaseModel) -> TaskResult:
        return TaskResult()


def test_registry_exposes_schema_and_validates_frozen_params() -> None:
    registry = TaskRegistry()
    registry.register(ExampleTask)

    descriptor = registry.get("test.example")
    params = descriptor.validate_params({"window": 14})

    assert descriptor.create().__class__ is ExampleTask
    assert descriptor.params_schema["properties"]["window"]["default"] == 7
    assert registry.descriptors == (descriptor,)
    assert params == WindowParams(window=14)
    with pytest.raises(ValidationError):
        params.window = 21
    with pytest.raises(ValidationError):
        descriptor.validate_params({"unexpected": True})


def test_duplicate_names_and_invalid_task_classes_fail_visibly() -> None:
    registry = TaskRegistry()
    registry.register(ExampleTask)

    with pytest.raises(TaskRegistryConflictError):
        registry.register(ExampleTask)

    class MutableParams(BaseModel):
        value: int = 1

    class InvalidTask(Task):
        name: ClassVar[str] = "test.invalid"
        display_name: ClassVar[str] = "Invalid"
        params_model: ClassVar[type[BaseModel]] = MutableParams

        async def run(self, context: object, params: BaseModel) -> TaskResult:
            return TaskResult()

    with pytest.raises(InvalidTaskError):
        registry.register(InvalidTask)


def test_frozen_params_with_extra_ignore_are_rejected_before_execution() -> None:
    class FrozenIgnoreParams(BaseModel):
        model_config = ConfigDict(frozen=True, extra="ignore")

        value: int = 1

    class FrozenIgnoreTask(ExampleTask):
        name: ClassVar[str] = "test.frozen-ignore"
        params_model: ClassVar[type[BaseModel]] = FrozenIgnoreParams

    registry = TaskRegistry()

    with pytest.raises(InvalidTaskError, match="extra.*forbid"):
        registry.register(FrozenIgnoreTask)


def test_builtin_discovery_is_idempotent_and_contains_history_purge() -> None:
    first = discover_tasks()
    second = discover_tasks()

    assert first is second
    assert first.get("system.purge_task_history").task_class is PurgeHistoryTask
    assert PurgeHistoryTask.params_model.model_config["frozen"] is True
    assert PurgeHistoryTask.params_model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "task_name",
    [
        "market.sync_a_daily",
        "market.sync_hk_daily",
        "market.sync_us_daily",
        "market.sync_crypto_daily",
    ],
)
def test_daily_sync_descriptors_expose_sync_parameters(task_name: str) -> None:
    descriptor = discover_tasks().get(task_name)

    properties = descriptor.params_schema["properties"]
    assert {
        "history_years",
        "overlap_days",
        "concurrency",
        "adjustment",
    } <= properties.keys()
    assert properties["overlap_days"]["default"] == 45
    assert properties["concurrency"]["default"] == 1
    assert properties["adjustment"]["default"] == "auto"


def test_only_crypto_daily_descriptor_exposes_structured_spot_pairs() -> None:
    registry = discover_tasks()
    crypto_properties = registry.get("market.sync_crypto_daily").params_schema[
        "properties"
    ]

    assert crypto_properties["spot_pairs"]["type"] == "array"
    assert crypto_properties["spot_pairs"]["default"] == []
    assert crypto_properties["spot_pairs"]["items"]["$ref"] == "#/$defs/CryptoSymbol"
    crypto_schema = registry.get("market.sync_crypto_daily").params_schema
    pair_definition = crypto_schema["$defs"]["CryptoSymbol"]
    assert pair_definition["type"] == "object"
    assert set(pair_definition["properties"]) == {"exchange", "symbol"}
    for task_name in (
        "market.sync_a_daily",
        "market.sync_hk_daily",
        "market.sync_us_daily",
    ):
        assert "spot_pairs" not in registry.get(task_name).params_schema["properties"]


def test_task_result_is_frozen_and_rejects_non_terminal_states() -> None:
    result = TaskResult(status="partial", progress=40, error="one item failed")

    with pytest.raises(ValidationError):
        result.status = "success"
    with pytest.raises(ValidationError):
        TaskResult(status="running")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TaskResult(progress=float("nan"))


def test_parameter_validation_rejects_non_finite_json_numbers() -> None:
    class FloatParams(TaskParams):
        value: float = 1.0

    class FloatTask(ExampleTask):
        name: ClassVar[str] = "test.float"
        params_model: ClassVar[type[BaseModel]] = FloatParams

    registry = TaskRegistry()
    registry.register(FloatTask)

    with pytest.raises(ValueError):
        registry.get(FloatTask.name).validate_params({"value": float("nan")})
    with pytest.raises(ValueError):
        registry.get(FloatTask.name).validate_params({"value": float("inf")})


def test_registry_rejects_non_frozen_custom_parameter_models() -> None:
    class NotFrozen(TaskParams):
        model_config = ConfigDict(extra="forbid", frozen=False)

    class NotFrozenTask(ExampleTask):
        name: ClassVar[str] = "test.not-frozen"
        params_model: ClassVar[type[BaseModel]] = NotFrozen

    registry = TaskRegistry()

    with pytest.raises(InvalidTaskError, match="frozen"):
        registry.register(NotFrozenTask)
