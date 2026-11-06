"""Standard Cron calculations and one-shot scheduler reconciliation."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from apscheduler.events import EVENT_JOB_ADDED, JobEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from pydantic import BaseModel

from app.config.defaults import default_settings
from app.config.models import Settings, TaskSettings
from app.services.cron_scheduler import CronScheduler, next_run_after
from app.tasks.base import Task, TaskParams, TaskResult
from app.tasks.registry import TaskRegistry, UnknownTaskError


class ScheduledParams(TaskParams):
    value: int = 1


class ScheduledTask(Task):
    name: ClassVar[str] = "test.scheduled"
    display_name: ClassVar[str] = "Scheduled"
    description: ClassVar[str] = "Scheduled test task"
    params_model: ClassVar[type[BaseModel]] = ScheduledParams

    async def run(self, context: object, params: BaseModel) -> TaskResult:
        return TaskResult()


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.called = asyncio.Event()

    async def start(
        self, task_name: str, trigger: str, params_override: object = None
    ) -> None:
        self.calls.append((task_name, trigger))
        self.called.set()


def configured(task: TaskSettings) -> Settings:
    return default_settings().model_copy(update={"tasks": {ScheduledTask.name: task}})


def make_scheduler(
    runner: RecordingRunner,
    now: datetime | Callable[[], datetime],
) -> tuple[CronScheduler, AsyncIOScheduler]:
    registry = TaskRegistry()
    registry.register(ScheduledTask)
    apscheduler = AsyncIOScheduler(timezone=UTC)
    clock = (lambda: now) if isinstance(now, datetime) else now
    scheduler = CronScheduler(
        runner,  # type: ignore[arg-type]
        registry,
        scheduler=apscheduler,
        now=clock,
    )
    return scheduler, apscheduler


def test_sunday_zero_and_standard_dom_dow_or_semantics() -> None:
    monday = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)

    assert next_run_after("0 9 * * 0", monday, "UTC") == datetime(
        2026, 1, 11, 9, 0, tzinfo=UTC
    )
    assert next_run_after("0 0 13 * 5", monday, "UTC") == datetime(
        2026, 1, 9, 0, 0, tzinfo=UTC
    )
    thirteenth = datetime(2026, 1, 13, 0, 0, tzinfo=UTC)
    assert next_run_after("0 0 13 * 5", thirteenth, "UTC") == datetime(
        2026, 1, 16, 0, 0, tzinfo=UTC
    )


def test_next_run_uses_global_timezone_and_returns_aware_utc() -> None:
    naive_local = datetime(2026, 1, 5, 8, 0)

    assert next_run_after("0 9 * * *", naive_local, "Asia/Shanghai") == datetime(
        2026, 1, 5, 1, 0, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="five"):
        next_run_after("0 0 * * * *", naive_local, "UTC")
    with pytest.raises(ValueError, match="timezone"):
        next_run_after("0 0 * * *", naive_local, "Mars/Olympus_Mons")


def test_repeated_apply_is_idempotent_and_disable_removes_managed_job() -> None:
    now = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    runner = RecordingRunner()
    scheduler, apscheduler = make_scheduler(runner, now)
    enabled = configured(TaskSettings(enabled=True, cron="0 9 * * 0"))

    scheduler.apply_settings(enabled)
    first_trigger = apscheduler.get_jobs()[0].trigger
    scheduler.apply_settings(enabled)

    assert len(apscheduler.get_jobs()) == 1
    assert apscheduler.get_jobs()[0].trigger == first_trigger
    scheduler.apply_settings(configured(TaskSettings(enabled=False)))
    assert apscheduler.get_jobs() == []


def test_invalid_candidate_does_not_change_existing_jobs() -> None:
    now = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    scheduler, apscheduler = make_scheduler(RecordingRunner(), now)
    scheduler.apply_settings(configured(TaskSettings(enabled=True, cron="0 9 * * 0")))
    before = apscheduler.get_jobs()[0].trigger

    with pytest.raises(ValueError, match="Invalid task parameters"):
        scheduler.apply_settings(
            configured(TaskSettings(enabled=True, params={"unexpected": True}))
        )
    with pytest.raises(ValueError, match="five"):
        scheduler.apply_settings(
            configured(TaskSettings(enabled=True, cron="0 0 * * * *"))
        )
    unknown = default_settings().model_copy(
        update={"tasks": {"missing": TaskSettings(enabled=True)}}
    )
    with pytest.raises(UnknownTaskError):
        scheduler.apply_settings(unknown)

    assert len(apscheduler.get_jobs()) == 1
    assert apscheduler.get_jobs()[0].trigger == before


def future_job_listener(
    apscheduler: AsyncIOScheduler,
    job_id: str,
    original_run_date: datetime,
    ready: asyncio.Event,
) -> Callable[[JobEvent], None]:
    """Observe only a replacement strictly later than the original one-shot."""
    def on_job_added(event: JobEvent) -> None:
        if event.job_id != job_id:
            return
        job = apscheduler.get_job(job_id)
        trigger = getattr(job, "trigger", None)
        if isinstance(trigger, DateTrigger) and trigger.run_date > original_run_date:
            ready.set()

    return on_job_added


@pytest.mark.anyio
async def test_running_scheduler_executes_one_shot_and_reapply_keeps_one_job() -> None:
    runner = RecordingRunner()
    scheduler, apscheduler = make_scheduler(runner, lambda: datetime.now(UTC))
    settings = configured(TaskSettings(enabled=True, cron="* * * * *"))
    scheduler.apply_settings(settings)
    job_id = apscheduler.get_jobs()[0].id
    due = datetime.now(UTC) + timedelta(milliseconds=100)
    apscheduler.reschedule_job(job_id, trigger=DateTrigger(run_date=due))
    future_added = asyncio.Event()
    scheduler.start()
    apscheduler.add_listener(
        future_job_listener(
            apscheduler,
            job_id,
            due,
            future_added,
        ),
        EVENT_JOB_ADDED,
    )
    try:
        await asyncio.wait_for(runner.called.wait(), timeout=2)
        await asyncio.wait_for(future_added.wait(), timeout=2)

        assert runner.calls == [(ScheduledTask.name, "scheduled")]
        assert len(apscheduler.get_jobs()) == 1
        assert apscheduler.get_jobs()[0].trigger.run_date > datetime.now(UTC)
        scheduler.apply_settings(settings)
        assert len(apscheduler.get_jobs()) == 1
        assert runner.calls == [(ScheduledTask.name, "scheduled")]
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.anyio
async def test_running_scheduler_misfire_skips_replay_and_schedules_future() -> None:
    runner = RecordingRunner()
    scheduler, apscheduler = make_scheduler(runner, lambda: datetime.now(UTC))
    settings = configured(TaskSettings(enabled=True, cron="* * * * *"))
    scheduler.apply_settings(settings)
    job_id = apscheduler.get_jobs()[0].id
    past = datetime.now(UTC) - timedelta(seconds=30)
    apscheduler.reschedule_job(job_id, trigger=DateTrigger(run_date=past))
    future_added = asyncio.Event()
    apscheduler.add_listener(
        future_job_listener(
            apscheduler,
            job_id,
            past,
            future_added,
        ),
        EVENT_JOB_ADDED,
    )
    scheduler.start()
    try:
        await asyncio.wait_for(future_added.wait(), timeout=2)

        assert runner.calls == []
        assert not runner.called.is_set()
        assert len(apscheduler.get_jobs()) == 1
        assert apscheduler.get_jobs()[0].trigger.run_date > datetime.now(UTC)
        scheduler.apply_settings(settings)
        assert len(apscheduler.get_jobs()) == 1
        assert runner.calls == []
    finally:
        scheduler.shutdown(wait=False)
