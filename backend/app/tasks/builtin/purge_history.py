"""Retention maintenance for Task runs and their cascading structured logs."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, Field

from app.tasks.base import (
    Task,
    TaskContext,
    TaskParams,
    TaskResult,
    require_task_params,
)
from app.tasks.registry import register_task

DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3_650


class PurgeHistoryParams(TaskParams):
    retention_days: int = Field(
        default=DEFAULT_RETENTION_DAYS,
        ge=1,
        le=MAX_RETENTION_DAYS,
    )


@register_task
class PurgeHistoryTask(Task):
    name: ClassVar[str] = "system.purge_task_history"
    display_name: ClassVar[str] = "Purge Task history"
    description: ClassVar[str] = "Delete Task runs and logs older than retention"
    params_model: ClassVar[type[BaseModel]] = PurgeHistoryParams

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        validated = require_task_params(params, PurgeHistoryParams)
        cutoff = datetime.now(UTC) - timedelta(days=validated.retention_days)
        deleted = context.task_runs.delete_before(cutoff)
        details = {
            "deleted_runs": deleted,
            "retention_days": validated.retention_days,
            "cutoff": cutoff.isoformat(),
        }
        context.log("INFO", "Task history purged", details)
        return TaskResult(details=details)
