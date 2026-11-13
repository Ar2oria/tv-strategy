"""CRUD for task runs, retention, restart recovery, and structured logs."""

from copy import deepcopy
from datetime import datetime
from enum import Enum, auto
from math import isfinite
from typing import Any, Literal

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.db.database import SessionFactory
from app.db.types import utc_now
from app.domain.dto import TaskLogDTO, TaskRunDTO, TaskStatus, TriggerType
from app.models.task_run import TaskLog, TaskRun

INTERRUPTION_MESSAGE = "Interrupted by application restart"
TERMINAL_RUN_STATUSES = frozenset(
    {"success", "partial", "failed", "skipped", "interrupted"}
)
MAX_PAGE_SIZE = 1000


class TaskRunNotFoundError(LookupError):
    """Raised when an operation requires a missing task run."""


class TaskLogNotFoundError(LookupError):
    """Raised when an operation requires a missing task log."""


class _Unset(Enum):
    VALUE = auto()


_UNSET = _Unset.VALUE


def _run_dto(run: TaskRun) -> TaskRunDTO:
    return TaskRunDTO(
        id=run.id,
        task_name=run.task_name,
        trigger=run.trigger,
        status=run.status,
        params=deepcopy(run.params),
        config_snapshot=deepcopy(run.config_snapshot),
        progress=run.progress,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _log_dto(log: TaskLog) -> TaskLogDTO:
    return TaskLogDTO(
        id=log.id,
        run_id=log.run_id,
        level=log.level,
        message=log.message,
        context=deepcopy(log.context),
        created_at=log.created_at,
    )


def _validate_page(limit: int | None, offset: int) -> None:
    if limit is not None and not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must not be negative")


class TaskRunRepository:
    """Own task history transactions and return detached DTO snapshots."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    @staticmethod
    def _require_run(session: Session, run_id: int) -> TaskRun:
        run = session.get(TaskRun, run_id)
        if run is None:
            raise TaskRunNotFoundError(f"Task run {run_id} does not exist")
        return run

    @staticmethod
    def _require_log(session: Session, log_id: int) -> TaskLog:
        log = session.get(TaskLog, log_id)
        if log is None:
            raise TaskLogNotFoundError(f"Task log {log_id} does not exist")
        return log

    def create_run(
        self,
        task_name: str,
        trigger: TriggerType,
        *,
        params: dict[str, Any] | None = None,
        config_snapshot: dict[str, Any] | None = None,
        status: TaskStatus = "queued",
        created_at: datetime | None = None,
    ) -> TaskRunDTO:
        with self._sessions() as session:
            with session.begin():
                result = session.execute(
                    insert(TaskRun).values(
                        task_name=task_name,
                        trigger=trigger,
                        status=status,
                        params=deepcopy(params) if params is not None else {},
                        config_snapshot=deepcopy(config_snapshot),
                        progress=0.0,
                        created_at=created_at if created_at is not None else utc_now(),
                    )
                )
                run_id = int(result.inserted_primary_key[0])
                return _run_dto(self._require_run(session, run_id))

    def get_run(self, run_id: int) -> TaskRunDTO | None:
        with self._sessions() as session:
            run = session.get(TaskRun, run_id)
            return None if run is None else _run_dto(run)

    def list_runs(
        self,
        task_name: str | None = None,
        *,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[TaskRunDTO]:
        _validate_page(limit, offset)
        statement = select(TaskRun)
        if task_name is not None:
            statement = statement.where(TaskRun.task_name == task_name)
        statement = statement.order_by(
            TaskRun.created_at.desc(), TaskRun.id.desc()
        ).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        with self._sessions() as session:
            return [_run_dto(run) for run in session.scalars(statement).all()]

    def count_runs(self, task_name: str | None = None) -> int:
        statement = select(func.count()).select_from(TaskRun)
        if task_name is not None:
            statement = statement.where(TaskRun.task_name == task_name)
        with self._sessions() as session:
            return int(session.scalar(statement) or 0)

    def update_run(
        self,
        run_id: int,
        *,
        status: TaskStatus | None = None,
        progress: float | None = None,
        error: str | None | _Unset = _UNSET,
        started_at: datetime | None | _Unset = _UNSET,
        finished_at: datetime | None | _Unset = _UNSET,
    ) -> TaskRunDTO:
        values: dict[str, Any] = {}
        if status is not None:
            values["status"] = status
        if progress is not None:
            if not isfinite(progress) or not 0 <= progress <= 100:
                raise ValueError("progress must be finite and between 0 and 100")
            values["progress"] = progress
        if error is not _UNSET:
            values["error"] = error
        if started_at is not _UNSET:
            values["started_at"] = started_at
        if finished_at is not _UNSET:
            values["finished_at"] = finished_at

        with self._sessions() as session:
            with session.begin():
                self._require_run(session, run_id)
                if values:
                    session.execute(
                        update(TaskRun).where(TaskRun.id == run_id).values(**values)
                    )
                    session.expire_all()
                return _run_dto(self._require_run(session, run_id))

    def delete_run(self, run_id: int) -> bool:
        with self._sessions() as session:
            with session.begin():
                result = session.execute(delete(TaskRun).where(TaskRun.id == run_id))
                return result.rowcount == 1

    def mark_stale_interrupted(self) -> int:
        """Mark previous-process queued and running rows interrupted."""
        with self._sessions() as session:
            with session.begin():
                result = session.execute(
                    update(TaskRun)
                    .where(TaskRun.status.in_(("queued", "running")))
                    .values(
                        status="interrupted",
                        error=INTERRUPTION_MESSAGE,
                        finished_at=utc_now(),
                    )
                )
                return int(result.rowcount)

    def delete_before(self, cutoff: datetime) -> int:
        """Delete only old terminal runs; enabled foreign keys cascade logs."""
        with self._sessions() as session:
            with session.begin():
                result = session.execute(
                    delete(TaskRun).where(
                        TaskRun.created_at < cutoff,
                        TaskRun.status.in_(TERMINAL_RUN_STATUSES),
                    )
                )
                return int(result.rowcount)

    def create_log(
        self,
        run_id: int,
        level: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> TaskLogDTO:
        with self._sessions() as session:
            with session.begin():
                self._require_run(session, run_id)
                result = session.execute(
                    insert(TaskLog).values(
                        run_id=run_id,
                        level=level,
                        message=message,
                        context=deepcopy(context) if context is not None else {},
                        created_at=created_at if created_at is not None else utc_now(),
                    )
                )
                log_id = int(result.inserted_primary_key[0])
                return _log_dto(self._require_log(session, log_id))

    def add_log(
        self,
        run_id: int,
        level: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> TaskLogDTO:
        """Task-context friendly alias for create_log."""
        return self.create_log(
            run_id,
            level,
            message,
            context=context,
            created_at=created_at,
        )

    def get_log(self, log_id: int) -> TaskLogDTO | None:
        with self._sessions() as session:
            log = session.get(TaskLog, log_id)
            return None if log is None else _log_dto(log)

    def list_logs(
        self,
        run_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
        order: Literal["asc", "desc"] = "asc",
    ) -> list[TaskLogDTO]:
        _validate_page(limit, offset)
        if order not in {"asc", "desc"}:
            raise ValueError("order must be asc or desc")
        ordering = (
            (TaskLog.created_at, TaskLog.id)
            if order == "asc"
            else (TaskLog.created_at.desc(), TaskLog.id.desc())
        )
        statement = (
            select(TaskLog)
            .where(TaskLog.run_id == run_id)
            .order_by(*ordering)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        with self._sessions() as session:
            return [_log_dto(log) for log in session.scalars(statement).all()]

    def count_logs(self, run_id: int) -> int:
        statement = select(func.count()).select_from(TaskLog).where(TaskLog.run_id == run_id)
        with self._sessions() as session:
            return int(session.scalar(statement) or 0)

    def update_log(
        self,
        log_id: int,
        *,
        level: str | None = None,
        message: str | None = None,
        context: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> TaskLogDTO:
        values: dict[str, Any] = {}
        if level is not None:
            values["level"] = level
        if message is not None:
            values["message"] = message
        if context is not None:
            values["context"] = deepcopy(context)
        if created_at is not None:
            values["created_at"] = created_at
        with self._sessions() as session:
            with session.begin():
                self._require_log(session, log_id)
                if values:
                    session.execute(
                        update(TaskLog).where(TaskLog.id == log_id).values(**values)
                    )
                    session.expire_all()
                return _log_dto(self._require_log(session, log_id))

    def delete_log(self, log_id: int) -> bool:
        with self._sessions() as session:
            with session.begin():
                result = session.execute(delete(TaskLog).where(TaskLog.id == log_id))
                return result.rowcount == 1
