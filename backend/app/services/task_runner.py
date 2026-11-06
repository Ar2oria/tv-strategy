"""Shared asynchronous Task runner with durable history and overlap skipping."""

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config.models import Settings, TaskSettings
from app.config.store import ConfigService
from app.db.types import utc_now
from app.domain.dto import TaskRunDTO, TaskStatus, TriggerType
from app.repositories.task_runs import TaskRunRepository
from app.services.resources import RuntimeResources
from app.tasks.base import TaskResult
from app.tasks.context import TaskContext
from app.tasks.registry import TaskDescriptor, TaskRegistry, UnknownTaskError

logger = logging.getLogger(__name__)

TASK_EXECUTION_ERROR = "Task execution failed"
TASK_INTERRUPTED_ERROR = "Task execution interrupted"
TASK_OVERLAP_ERROR = "Task is already running"
TRIGGERS = frozenset({"manual", "scheduled"})
ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})
SettingsSource = Settings | ConfigService | Callable[[], Settings]


class TaskParameterError(ValueError):
    """Task parameters failed JSON or concrete model validation."""

    def __init__(self) -> None:
        super().__init__("Invalid task parameters")


def _result_error(result: TaskResult) -> str | None:
    if result.status == "success":
        return None
    if result.status == "failed":
        return result.error or TASK_EXECUTION_ERROR
    return result.error


class TaskRunner:
    """Create runs immediately and execute each Task at most once at a time."""

    def __init__(
        self,
        registry: TaskRegistry,
        task_runs: TaskRunRepository,
        settings: SettingsSource,
        resources: RuntimeResources,
    ) -> None:
        self._registry = registry
        self._runs = task_runs
        self._settings_source = settings
        self._resources = resources
        self._running: dict[str, int] = {}
        self._background: frozenset[asyncio.Task[None]] = frozenset()
        self._lock = asyncio.Lock()
        self._runs.mark_stale_interrupted()

    @property
    def resources(self) -> RuntimeResources:
        """Return the immutable snapshot used by newly starting Tasks."""
        return self._resources

    def replace_resources(self, resources: RuntimeResources) -> None:
        """Atomically point new executions at a rebuilt runtime snapshot."""
        if not isinstance(resources, RuntimeResources):
            raise TypeError("resources must be RuntimeResources")
        self._resources = resources

    async def start(
        self,
        task_name: str,
        trigger: TriggerType,
        params_override: dict[str, Any] | None = None,
    ) -> TaskRunDTO:
        """Persist a run and return before its background execution completes."""
        if trigger not in TRIGGERS:
            raise ValueError(f"Unsupported Task trigger: {trigger!r}")
        descriptor = self._registry.get(task_name)
        settings = self._read_settings()
        resources = self._resources
        task_settings = settings.tasks.get(task_name, TaskSettings())
        configured = dict(task_settings.params)
        if params_override is not None and not isinstance(params_override, dict):
            raise TaskParameterError()
        supplied = dict(params_override) if params_override is not None else {}
        merged = {**configured, **supplied}
        params = self._validate_params(descriptor, merged)
        params_snapshot = params.model_dump(mode="json")
        config_snapshot = task_settings.model_dump(mode="json")

        async with self._lock:
            if task_name in self._running:
                return self._create_skipped(
                    task_name, trigger, params_snapshot, config_snapshot
                )
            run = self._runs.create_run(
                task_name,
                trigger,
                params=params_snapshot,
                config_snapshot=config_snapshot,
            )
            self._running = {**self._running, task_name: run.id}
            try:
                execution = asyncio.create_task(
                    self._execute(
                        descriptor,
                        run.id,
                        settings,
                        params,
                        resources,
                    )
                )
            except Exception:
                self._release_guard(task_name, run.id)
                self._runs.update_run(
                    run.id,
                    status="failed",
                    error=TASK_EXECUTION_ERROR,
                    finished_at=utc_now(),
                )
                raise
            self._background = self._background | {execution}
            execution.add_done_callback(
                partial(
                    self._execution_done,
                    task_name=task_name,
                    run_id=run.id,
                )
            )
            return run

    def validate_settings(self, settings: Settings) -> None:
        """Validate all registered params and reject enabled unknown Tasks."""
        for name, task_settings in settings.tasks.items():
            try:
                descriptor = self._registry.get(name)
            except UnknownTaskError:
                if task_settings.enabled:
                    raise
                continue
            self._validate_params(descriptor, dict(task_settings.params))

    async def wait_for_idle(self) -> None:
        """Test/lifespan hook that waits until currently queued work finishes."""
        while True:
            async with self._lock:
                pending = tuple(self._background)
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    async def aclose(self) -> None:
        """Allow in-flight Tasks to finish during an orderly lifespan shutdown."""
        await self.wait_for_idle()

    def _read_settings(self) -> Settings:
        if isinstance(self._settings_source, Settings):
            return self._settings_source.model_copy(deep=True)
        if isinstance(self._settings_source, ConfigService):
            return self._settings_source.get()
        settings = self._settings_source()
        if not isinstance(settings, Settings):
            raise TypeError("Task settings source must return Settings")
        return settings.model_copy(deep=True)

    @staticmethod
    def _validate_params(
        descriptor: TaskDescriptor, values: dict[str, Any]
    ) -> BaseModel:
        try:
            return descriptor.validate_params(values)
        except (ValidationError, TypeError, ValueError):
            logger.info("Invalid parameters for Task %s", descriptor.name)
            raise TaskParameterError() from None
        except Exception:
            logger.exception(
                "Unexpected parameter validation failure for Task %s", descriptor.name
            )
            raise TaskParameterError() from None

    def _create_skipped(
        self,
        task_name: str,
        trigger: TriggerType,
        params: dict[str, Any],
        config_snapshot: dict[str, Any],
    ) -> TaskRunDTO:
        skipped = self._runs.create_run(
            task_name,
            trigger,
            params=params,
            config_snapshot=config_snapshot,
            status="skipped",
        )
        return self._runs.update_run(
            skipped.id,
            status="skipped",
            error=TASK_OVERLAP_ERROR,
            finished_at=utc_now(),
        )

    async def _execute(
        self,
        descriptor: TaskDescriptor,
        run_id: int,
        settings: Settings,
        params: BaseModel,
        resources: RuntimeResources,
    ) -> None:
        try:
            self._runs.update_run(
                run_id, status="running", started_at=utc_now(), error=None
            )
            context = TaskContext(
                run_id=run_id,
                settings=settings.model_copy(deep=True),
                resources=resources,
                runs=self._runs,
            )
            result = await descriptor.create().run(context, params)
            if not isinstance(result, TaskResult):
                raise TypeError(
                    f"Task {descriptor.name!r} returned {type(result).__name__} "
                    "instead of TaskResult"
                )
            self._runs.update_run(
                run_id,
                status=result.status,
                progress=result.progress,
                error=_result_error(result),
                finished_at=utc_now(),
            )
        except asyncio.CancelledError:
            self._finish_after_error(run_id, "interrupted", TASK_INTERRUPTED_ERROR)
            raise
        except Exception:
            logger.exception(
                "Task %s execution failed for run %s", descriptor.name, run_id
            )
            self._safe_error_log(run_id)
            self._finish_after_error(run_id, "failed", TASK_EXECUTION_ERROR)
        finally:
            async with self._lock:
                self._release_guard(descriptor.name, run_id)

    def _finish_after_error(
        self, run_id: int, status: TaskStatus, message: str
    ) -> None:
        try:
            current = self._runs.get_run(run_id)
            progress = current.progress if current is not None else 0.0
            self._runs.update_run(
                run_id,
                status=status,
                progress=progress,
                error=message,
                finished_at=utc_now(),
            )
        except Exception:
            logger.exception("Unable to persist terminal state for Task run %s", run_id)

    def _safe_error_log(self, run_id: int) -> None:
        try:
            self._runs.add_log(run_id, "ERROR", TASK_EXECUTION_ERROR)
        except Exception:
            logger.exception("Unable to persist failure log for Task run %s", run_id)

    def _release_guard(self, task_name: str, run_id: int) -> None:
        """Release only the guard owned by this exact run, never a newer run."""
        if self._running.get(task_name) != run_id:
            return
        self._running = {
            name: owner for name, owner in self._running.items() if name != task_name
        }

    def _interrupt_active_run(self, run_id: int) -> None:
        """Persist cancellation only when execution has not reached a terminal state."""
        try:
            run = self._runs.get_run(run_id)
            if run is None or run.status not in ACTIVE_RUN_STATUSES:
                return
            self._runs.update_run(
                run_id,
                status="interrupted",
                error=TASK_INTERRUPTED_ERROR,
                finished_at=utc_now(),
            )
        except Exception:
            logger.exception("Unable to interrupt cancelled Task run %s", run_id)

    def _execution_done(
        self,
        execution: asyncio.Task[None],
        *,
        task_name: str,
        run_id: int,
    ) -> None:
        self._background = self._background - {execution}
        try:
            if execution.cancelled():
                # A task cancelled before its first coroutine step never enters
                # _execute, so this callback owns its terminal cleanup.
                self._interrupt_active_run(run_id)
                return
            error = execution.exception()
            if error is not None:
                logger.error(
                    "Task background wrapper failed: %s",
                    error,
                    exc_info=(type(error), error, error.__traceback__),
                )
        finally:
            self._release_guard(task_name, run_id)
