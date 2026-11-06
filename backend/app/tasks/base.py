"""The single asynchronous execution contract implemented by every Task."""

from abc import ABC, abstractmethod
from typing import ClassVar, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.tasks.context import TaskContext

TerminalTaskStatus = Literal["success", "partial", "failed"]
ParamsT = TypeVar("ParamsT", bound=BaseModel)


class TaskParams(BaseModel):
    """Frozen parameters with unknown fields rejected at the Task boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskResult(BaseModel):
    """Immutable terminal outcome returned by a Task implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TerminalTaskStatus = "success"
    progress: float = Field(default=100, ge=0, le=100, allow_inf_nan=False)
    error: str | None = Field(default=None, max_length=2_000)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class Task(ABC):
    """A uniquely named class with one config and one async run entry."""

    name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    params_model: ClassVar[type[BaseModel]] = TaskParams

    @abstractmethod
    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        """Execute once and return a new immutable terminal result."""


def require_task_params(params: BaseModel, expected: type[ParamsT]) -> ParamsT:
    """Reject unvalidated parameter objects at a concrete Task boundary."""
    if not isinstance(params, expected):
        raise TypeError(
            f"Expected {expected.__name__}, received {type(params).__name__}"
        )
    return params


__all__ = [
    "Task",
    "TaskContext",
    "TaskParams",
    "TaskResult",
    "TerminalTaskStatus",
    "require_task_params",
]
