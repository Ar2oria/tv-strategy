"""Standard five-field Cron calculations and one-shot APScheduler jobs."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.events import EVENT_JOB_MISSED, JobEvent
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from croniter import croniter
from pydantic import ValidationError

from app.config.models import CRON_FIELD_COUNT, Settings
from app.db.types import utc_now
from app.services.task_runner import TaskRunner
from app.tasks.registry import TaskRegistry, UnknownTaskError

logger = logging.getLogger(__name__)

JOB_ID_PREFIX = "task-cron:"
MISFIRE_GRACE_SECONDS = 1


@dataclass(frozen=True, slots=True)
class _SchedulePlan:
    task_name: str
    cron: str
    timezone: str
    run_time: datetime

    @property
    def job_id(self) -> str:
        return f"{JOB_ID_PREFIX}{self.task_name}"


def next_run_after(expression: str, after: datetime, timezone: str) -> datetime:
    """Return the next standard Cron occurrence as an aware UTC datetime."""
    if not isinstance(expression, str) or len(expression.split()) != CRON_FIELD_COUNT:
        raise ValueError("Cron expression must contain exactly five fields")
    if not isinstance(after, datetime):
        raise TypeError("after must be a datetime")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise ValueError(f"Invalid IANA timezone: {timezone!r}") from error
    local_after = (
        after.replace(tzinfo=zone) if after.tzinfo is None else after.astimezone(zone)
    )
    try:
        occurrence = croniter(
            expression,
            local_after,
            day_or=True,
        ).get_next(datetime)
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError(f"Invalid cron expression: {expression!r}") from error
    if occurrence.tzinfo is None:
        occurrence = occurrence.replace(tzinfo=zone)
    return occurrence.astimezone(UTC)


class CronScheduler:
    """Reconcile enabled Tasks with one future DateTrigger job per Task."""

    def __init__(
        self,
        runner: TaskRunner,
        registry: TaskRegistry,
        *,
        scheduler: AsyncIOScheduler | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._runner = runner
        self._registry = registry
        self._scheduler = scheduler or AsyncIOScheduler(timezone=UTC)
        self._now = now
        self._settings: Settings | None = None
        self._lock = threading.RLock()
        self._scheduler.add_listener(self._job_missed, EVENT_JOB_MISSED)

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self, *, wait: bool = True) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    def apply_settings(self, settings: Settings) -> None:
        """Validate and precompute every job before changing managed jobs."""
        if not isinstance(settings, Settings):
            raise TypeError("CronScheduler settings must be a Settings instance")
        validated = Settings.model_validate(settings.model_dump(mode="python"))
        self._validate_task_settings(validated)
        after = self._now()
        plans = tuple(
            self._plan(name, task_settings.cron, validated.timezone, after)
            for name, task_settings in sorted(validated.tasks.items())
            if task_settings.enabled
        )
        # Construct every trigger before reconciliation to fail without mutation.
        for plan in plans:
            DateTrigger(run_date=plan.run_time, timezone=UTC)

        with self._lock:
            desired_ids = {plan.job_id for plan in plans}
            existing = {
                job.id: job
                for job in self._scheduler.get_jobs()
                if job.id.startswith(JOB_ID_PREFIX)
            }
            for plan in plans:
                current = existing.get(plan.job_id)
                if current is not None and self._matches(current, plan):
                    continue
                self._add_job(plan)
            for job_id in sorted(set(existing) - desired_ids):
                try:
                    self._scheduler.remove_job(job_id)
                except JobLookupError:
                    # A one-shot job may finish between listing and removal.
                    pass
            self._settings = validated.model_copy(deep=True)

    def _validate_task_settings(self, settings: Settings) -> None:
        for name, task_settings in settings.tasks.items():
            try:
                descriptor = self._registry.get(name)
            except UnknownTaskError:
                if task_settings.enabled:
                    raise
                continue
            try:
                descriptor.validate_params(dict(task_settings.params))
            except (ValidationError, TypeError, ValueError):
                logger.info("Invalid configured parameters for Task %s", name)
                raise ValueError("Invalid task parameters") from None
            except Exception:
                logger.exception("Task parameter validation failed for %s", name)
                raise ValueError("Invalid task parameters") from None

    def _plan(
        self, task_name: str, cron: str, timezone: str, after: datetime
    ) -> _SchedulePlan:
        # Resolution also rejects enabled names missing from the registry.
        self._registry.get(task_name)
        run_time = next_run_after(cron, after, timezone)
        return _SchedulePlan(task_name, cron, timezone, run_time)

    def _matches(self, job: object, plan: _SchedulePlan) -> bool:
        trigger = getattr(job, "trigger", None)
        args = getattr(job, "args", ())
        return (
            isinstance(trigger, DateTrigger)
            and trigger.run_date == plan.run_time
            and tuple(args) == (plan.task_name, plan.cron, plan.timezone)
        )

    def _add_job(self, plan: _SchedulePlan) -> None:
        # Pending APScheduler jobs are deduplicated only when the scheduler
        # starts, so remove the old pending/running entry explicitly as well.
        for existing in self._scheduler.get_jobs():
            if existing.id != plan.job_id:
                continue
            try:
                self._scheduler.remove_job(plan.job_id)
            except JobLookupError:
                pass
        self._scheduler.add_job(
            self._run_due,
            trigger=DateTrigger(run_date=plan.run_time, timezone=UTC),
            args=(plan.task_name, plan.cron, plan.timezone),
            id=plan.job_id,
            name=f"Scheduled Task {plan.task_name}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )

    def _job_missed(self, event: JobEvent) -> None:
        """Skip missed downtime but keep the recurring schedule alive."""
        if not event.job_id.startswith(JOB_ID_PREFIX):
            return
        task_name = event.job_id.removeprefix(JOB_ID_PREFIX)
        with self._lock:
            settings = self._settings
            task_settings = (
                settings.tasks.get(task_name) if settings is not None else None
            )
            if settings is None or task_settings is None or not task_settings.enabled:
                return
            try:
                plan = self._plan(
                    task_name,
                    task_settings.cron,
                    settings.timezone,
                    self._now(),
                )
                self._add_job(plan)
            except Exception:
                logger.exception(
                    "Unable to schedule the next occurrence after a missed Task %s",
                    task_name,
                )

    async def _run_due(self, task_name: str, cron: str, timezone: str) -> None:
        """Share runner overlap semantics, then schedule only a future occurrence."""
        try:
            await self._runner.start(task_name, "scheduled")
        except Exception:
            logger.exception("Scheduled start failed for Task %s", task_name)
        finally:
            with self._lock:
                settings = self._settings
                if settings is None:
                    return
                task_settings = settings.tasks.get(task_name)
                if (
                    task_settings is None
                    or not task_settings.enabled
                    or task_settings.cron != cron
                    or settings.timezone != timezone
                ):
                    return
                try:
                    plan = self._plan(task_name, cron, timezone, self._now())
                    self._add_job(plan)
                except Exception:
                    logger.exception(
                        "Unable to schedule the next occurrence for Task %s",
                        task_name,
                    )
