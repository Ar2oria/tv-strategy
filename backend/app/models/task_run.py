"""Task execution history and structured log tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, String
from sqlalchemy import Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utc_now
from app.domain.dto import TaskStatus, TriggerType

TRIGGER_CHECK = "trigger IN ('manual', 'scheduled')"
STATUS_CHECK = (
    "status IN ('queued', 'running', 'success', 'partial', 'failed', "
    "'skipped', 'interrupted')"
)
PROGRESS_CHECK = "progress >= 0 AND progress <= 100"


class TaskRun(Base):
    """One queued or completed execution of a named task."""

    __tablename__ = "task_runs"
    __table_args__ = (
        CheckConstraint(TRIGGER_CHECK, name="valid_trigger"),
        CheckConstraint(STATUS_CHECK, name="valid_status"),
        CheckConstraint(PROGRESS_CHECK, name="valid_progress"),
        Index("ix_task_runs_task_name_id", "task_name", "id"),
        Index("ix_task_runs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_name: Mapped[str] = mapped_column(String(256), nullable=False)
    trigger: Mapped[TriggerType] = mapped_column(String(16), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    progress: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )


class TaskLog(Base):
    """A timestamped structured message belonging to one task run."""

    __tablename__ = "task_logs"
    __table_args__ = (Index("ix_task_logs_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
