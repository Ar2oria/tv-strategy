"""Redaction helpers for sensitive Task parameters."""

from copy import deepcopy
from typing import Any

from app.config.models import Settings, TaskSettings

# Run history must never expose a bearer token, even though the Task
# configuration itself persists the token for scheduled and manual runs.
SENSITIVE_TASK_PARAMS = frozenset({"itiger_token"})
SENSITIVE_PARAM_MASK = "********"


def redact_sensitive_task_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a new params object without bearer-token values."""
    return {
        key: value
        for key, value in params.items()
        if key not in SENSITIVE_TASK_PARAMS
    }


def mask_sensitive_task_params(params: dict[str, Any]) -> dict[str, Any]:
    """Mask persisted secrets while preserving editability and blank values."""
    return {
        key: (
            SENSITIVE_PARAM_MASK
            if key in SENSITIVE_TASK_PARAMS
            and isinstance(value, str)
            and value.strip()
            else deepcopy(value)
        )
        for key, value in params.items()
    }


def restore_sensitive_task_params(
    params: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Replace round-tripped masks with current secrets without mutating input."""
    restored = deepcopy(params)
    for key in SENSITIVE_TASK_PARAMS:
        if params.get(key) != SENSITIVE_PARAM_MASK:
            continue
        existing = current.get(key)
        if isinstance(existing, str) and existing.strip():
            restored = {**restored, key: existing}
        else:
            restored = {
                name: value for name, value in restored.items() if name != key
            }
    return restored


def mask_sensitive_settings(settings: Settings) -> Settings:
    """Return a new Settings snapshot with every persisted secret masked."""
    tasks = {
        name: task.model_copy(
            update={"params": mask_sensitive_task_params(task.params)}
        )
        for name, task in settings.tasks.items()
    }
    return settings.model_copy(deep=True, update={"tasks": tasks})


def restore_sensitive_settings(candidate: Settings, current: Settings) -> Settings:
    """Resolve API masks against the current document before validation/storage."""
    tasks = {
        name: task.model_copy(
            update={
                "params": restore_sensitive_task_params(
                    task.params,
                    current.tasks.get(name, TaskSettings()).params,
                )
            }
        )
        for name, task in candidate.tasks.items()
    }
    return candidate.model_copy(deep=True, update={"tasks": tasks})
