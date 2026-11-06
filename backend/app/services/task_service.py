"""Task catalog, revision-checked configuration, runs, and log queries."""

import logging
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.config.models import Settings, TaskSettings
from app.config.store import (
    ConfigService,
    ConfigValidationError,
)
from app.db.types import utc_now
from app.domain.dto import TaskLogDTO, TaskRunDTO
from app.repositories.task_runs import TaskRunNotFoundError, TaskRunRepository
from app.services.cron_scheduler import next_run_after
from app.services.task_runner import TaskRunner
from app.tasks.registry import TaskDescriptor, TaskRegistry

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 100
DEFAULT_LOG_LIMIT = 1_000


class InvalidTaskConfigError(ValueError):
    """A Task configuration violates Cron or parameter validation."""

    def __init__(self) -> None:
        super().__init__("Invalid task configuration")


class TaskView(BaseModel):
    """Immutable API-facing Task configuration and current run metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    display_name: str
    description: str
    enabled: bool
    cron: str
    params: dict[str, JsonValue]
    params_schema: dict[str, JsonValue] = Field(default_factory=dict)
    revision: int
    next_run_at: datetime | None = None
    last_run: TaskRunDTO | None = None


class TaskService:
    """Coordinate immutable configuration updates and execution requests."""

    def __init__(
        self,
        config: ConfigService,
        registry: TaskRegistry,
        task_runs: TaskRunRepository,
        runner: TaskRunner,
        *,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._config = config
        self._registry = registry
        self._runs = task_runs
        self._runner = runner
        self._now = now

    def list_tasks(self) -> list[TaskView]:
        settings = self._config.get()
        return [
            self._view(descriptor, settings)
            for descriptor in self._registry.descriptors
        ]

    def get_config(self, task_name: str) -> TaskView:
        descriptor = self._registry.get(task_name)
        return self._view(descriptor, self._config.get())

    def update_config(
        self,
        task_name: str,
        expected_revision: int,
        *,
        enabled: bool | None = None,
        cron: str | None = None,
        params: dict[str, JsonValue] | None = None,
    ) -> TaskView:
        descriptor = self._registry.get(task_name)
        changes = {
            key: value
            for key, value in {
                "enabled": enabled,
                "cron": cron,
                "params": params,
            }.items()
            if value is not None
        }
        if not changes:
            raise InvalidTaskConfigError()
        current = self._config.get().tasks.get(task_name, TaskSettings())
        try:
            candidate = TaskSettings.model_validate(
                {**current.model_dump(mode="python"), **changes}
            )
            descriptor.validate_params(dict(candidate.params))
        except (ValidationError, TypeError, ValueError):
            raise InvalidTaskConfigError() from None
        except Exception:
            logger.exception(
                "Unexpected config validation failure for Task %s", task_name
            )
            raise InvalidTaskConfigError() from None

        def build_next(old: Settings) -> Settings:
            existing = old.tasks.get(task_name, TaskSettings())
            updated = existing.model_copy(update=changes)
            next_settings = old.model_copy(
                update={"tasks": {**old.tasks, task_name: updated}}
            )
            self.validate_settings(next_settings)
            return next_settings

        try:
            settings = self._config.update(expected_revision, build_next)
        except ConfigValidationError:
            raise InvalidTaskConfigError() from None
        return self._view(descriptor, settings)

    async def run_now(
        self, task_name: str, params_override: dict | None = None
    ) -> TaskRunDTO:
        return await self._runner.start(task_name, "manual", params_override)

    def history(
        self,
        task_name: str,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
        offset: int = 0,
    ) -> list[TaskRunDTO]:
        self._registry.get(task_name)
        return self._runs.list_runs(task_name, limit=limit, offset=offset)

    def logs(
        self,
        run_id: int,
        *,
        limit: int = DEFAULT_LOG_LIMIT,
        offset: int = 0,
    ) -> list[TaskLogDTO]:
        if self._runs.get_run(run_id) is None:
            raise TaskRunNotFoundError(f"Task run {run_id} does not exist")
        return self._runs.list_logs(run_id, limit=limit, offset=offset)

    def validate_settings(self, settings: Settings) -> None:
        """ConfigService validator hook; performs no runtime job mutations."""
        self._runner.validate_settings(settings)
        for task_name, task_settings in settings.tasks.items():
            if task_settings.enabled:
                self._registry.get(task_name)
                next_run_after(task_settings.cron, self._now(), settings.timezone)

    def _view(self, descriptor: TaskDescriptor, settings: Settings) -> TaskView:
        task_settings = settings.tasks.get(descriptor.name, TaskSettings())
        history = self._runs.list_runs(descriptor.name, limit=1)
        next_run = (
            next_run_after(task_settings.cron, self._now(), settings.timezone)
            if task_settings.enabled
            else None
        )
        return TaskView(
            name=descriptor.name,
            display_name=descriptor.display_name,
            description=descriptor.description,
            enabled=task_settings.enabled,
            cron=task_settings.cron,
            params=task_settings.params,
            params_schema=descriptor.params_schema,
            revision=settings.revision,
            next_run_at=next_run,
            last_run=history[0] if history else None,
        )
