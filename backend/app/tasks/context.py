"""Frozen execution context for progress and structured Task logs."""

import json
from dataclasses import dataclass, field
from math import isfinite

from pydantic import JsonValue, TypeAdapter

from app.config.models import Settings
from app.domain.dto import TaskLogDTO, TaskRunDTO
from app.repositories.task_runs import TaskRunRepository
from app.services.resources import RuntimeResources

LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_LOG_CONTEXT = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class TaskContext:
    """One detached settings snapshot and its persistence capabilities."""

    run_id: int
    settings: Settings
    resources: RuntimeResources
    runs: TaskRunRepository = field(repr=False, compare=False)

    @property
    def task_runs(self) -> TaskRunRepository:
        """Explicit alias for maintenance Tasks such as history retention."""
        return self.runs

    def log(
        self,
        level: str,
        message: str,
        context: dict[str, JsonValue] | None = None,
        **details: JsonValue,
    ) -> TaskLogDTO:
        """Persist one JSON-safe structured log without exposing tracebacks."""
        if not isinstance(level, str) or level.upper() not in LOG_LEVELS:
            raise ValueError(f"Unsupported Task log level: {level!r}")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Task log message must not be blank")
        if context is not None and not isinstance(context, dict):
            raise TypeError("Task log context must be a dictionary")
        merged = {**(context or {}), **details}
        validated = _LOG_CONTEXT.validate_python(merged)
        json.dumps(validated, allow_nan=False)
        return self.runs.add_log(
            self.run_id,
            level.upper(),
            message,
            context=validated,
        )

    def report_progress(self, progress: float) -> TaskRunDTO:
        """Persist finite completion percentage in the inclusive 0-100 range."""
        if isinstance(progress, bool) or not isinstance(progress, (int, float)):
            raise TypeError("Task progress must be numeric")
        if not isfinite(progress) or not 0 <= progress <= 100:
            raise ValueError("Task progress must be finite and between 0 and 100")
        return self.runs.update_run(self.run_id, progress=float(progress))
