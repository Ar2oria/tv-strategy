"""Persistent asynchronous Task execution, overlap, and recovery tests."""

import asyncio
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from pydantic import BaseModel

from app.config.defaults import default_settings
from app.config.models import Settings, TaskSettings
from app.domain.dto import UniverseSnapshot
from app.providers.hstech_api import ItigerUniverseProvider
from app.providers.registry import ProviderRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.tasks.builtin.sync_universes import SyncUniversesTask
from tests.market_sync_fixtures import instrument_dto
from app.db.database import SessionFactory
from app.domain.dto import TaskRunDTO
from app.repositories.task_runs import TaskRunRepository
from app.services.resources import RuntimeResources
from app.services.task_runner import TASK_EXECUTION_ERROR, TaskRunner
from app.tasks.base import Task, TaskContext, TaskParams, TaskResult
from app.tasks.builtin.purge_history import PurgeHistoryTask
from app.tasks.registry import TaskRegistry


class ValueParams(TaskParams):
    value: int = 1


class BlockingTask(Task):
    name: ClassVar[str] = "test.blocking"
    display_name: ClassVar[str] = "Blocking"
    description: ClassVar[str] = "Blocks until released"
    params_model: ClassVar[type[BaseModel]] = ValueParams
    started: ClassVar[asyncio.Event]
    release: ClassVar[asyncio.Event]
    executions: ClassVar[list[int]] = []

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        assert isinstance(params, ValueParams)
        type(self).executions.append(params.value)
        context.log("INFO", "started", {"value": params.value})
        context.report_progress(25)
        type(self).started.set()
        await type(self).release.wait()
        context.log("INFO", "finished")
        return TaskResult()


class PartialTask(Task):
    name: ClassVar[str] = "test.partial"
    display_name: ClassVar[str] = "Partial"
    description: ClassVar[str] = "Returns partial progress"

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        context.report_progress(35)
        context.log("WARNING", "one item failed", symbol="AAA")
        return TaskResult(status="partial", progress=80, error="one item failed")


class FailedTask(Task):
    name: ClassVar[str] = "test.failed"
    display_name: ClassVar[str] = "Failed"
    description: ClassVar[str] = "Returns failure without details"

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        context.report_progress(60)
        return TaskResult(status="failed", progress=60)


class ExplodingTask(Task):
    name: ClassVar[str] = "test.exploding"
    display_name: ClassVar[str] = "Exploding"
    description: ClassVar[str] = "Raises a private exception"

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        context.report_progress(20)
        raise RuntimeError("private provider credential")


def settings_for(*tasks: tuple[str, TaskSettings]) -> Settings:
    return default_settings().model_copy(update={"tasks": dict(tasks)})


def make_runner(
    factory: SessionFactory,
    registry: TaskRegistry,
    settings: Settings,
) -> tuple[TaskRunner, TaskRunRepository]:
    runs = TaskRunRepository(factory)
    resources = RuntimeResources(
        instrument_repository=object(),
        bar_repository=object(),
    )
    return TaskRunner(registry, runs, settings, resources), runs


async def wait_for_run(
    runner: TaskRunner, runs: TaskRunRepository, run_id: int
) -> TaskRunDTO:
    await runner.wait_for_idle()
    result = runs.get_run(run_id)
    assert result is not None
    return result


@pytest.mark.anyio
async def test_overlap_creates_skipped_run_and_executes_only_once(
    session_factory: SessionFactory,
) -> None:
    BlockingTask.started = asyncio.Event()
    BlockingTask.release = asyncio.Event()
    BlockingTask.executions = []
    registry = TaskRegistry()
    registry.register(BlockingTask)
    settings = settings_for(
        (BlockingTask.name, TaskSettings(cron="0 9 * * 0", params={"value": 2}))
    )
    runner, runs = make_runner(session_factory, registry, settings)

    first = await runner.start(BlockingTask.name, "manual", {"value": 3})
    await asyncio.wait_for(BlockingTask.started.wait(), timeout=1)
    skipped = await runner.start(BlockingTask.name, "scheduled")
    assert skipped.status == "skipped"
    assert skipped.finished_at is not None
    BlockingTask.release.set()
    completed = await wait_for_run(runner, runs, first.id)

    assert BlockingTask.executions == [3]
    assert first.params == {"value": 3}
    assert first.config_snapshot == settings.tasks[BlockingTask.name].model_dump(
        mode="json"
    )
    assert completed.status == "success"
    assert completed.progress == 100
    assert completed.started_at is not None
    assert completed.finished_at is not None
    assert [log.message for log in runs.list_logs(first.id)] == ["started", "finished"]
    assert runs.list_logs(first.id)[0].context == {"value": 3}


@pytest.mark.anyio
async def test_cancel_before_first_step_interrupts_run_and_allows_restarts(
    session_factory: SessionFactory,
) -> None:
    registry = TaskRegistry()
    registry.register(PartialTask)
    runner, runs = make_runner(
        session_factory, registry, settings_for((PartialTask.name, TaskSettings()))
    )

    first = await runner.start(PartialTask.name, "manual")
    execution = next(iter(runner._background))
    execution.cancel()
    await asyncio.gather(execution, return_exceptions=True)
    await asyncio.wait_for(runner.wait_for_idle(), timeout=1)

    interrupted = runs.get_run(first.id)
    assert interrupted is not None
    assert interrupted.status == "interrupted"
    assert interrupted.error == "Task execution interrupted"
    assert interrupted.finished_at is not None

    second = await runner.start(PartialTask.name, "manual")
    completed = await wait_for_run(runner, runs, second.id)

    assert second.id != first.id
    assert completed.status == "partial"
    assert completed.progress == 80


@pytest.mark.anyio
async def test_partial_and_unexpected_failure_persist_safe_status_progress_and_logs(
    session_factory: SessionFactory,
) -> None:
    registry = TaskRegistry()
    registry.register(PartialTask)
    registry.register(ExplodingTask)
    registry.register(FailedTask)
    settings = settings_for(
        (PartialTask.name, TaskSettings()),
        (ExplodingTask.name, TaskSettings()),
        (FailedTask.name, TaskSettings()),
    )
    runner, runs = make_runner(session_factory, registry, settings)

    partial = await runner.start(PartialTask.name, "manual")
    failed = await runner.start(ExplodingTask.name, "scheduled")
    returned_failure = await runner.start(FailedTask.name, "manual")
    partial_result = await wait_for_run(runner, runs, partial.id)
    failed_result = await wait_for_run(runner, runs, failed.id)
    returned_failure_result = await wait_for_run(runner, runs, returned_failure.id)

    assert partial_result.status == "partial"
    assert partial_result.progress == 80
    assert partial_result.error == "one item failed"
    assert runs.list_logs(partial.id)[0].context == {"symbol": "AAA"}
    assert failed_result.status == "failed"
    assert failed_result.progress == 20
    assert failed_result.error == TASK_EXECUTION_ERROR
    assert "private provider credential" not in str(failed_result)
    failure_logs = runs.list_logs(failed.id)
    assert len(failure_logs) == 1
    assert failure_logs[0].context == {"error_type": "RuntimeError"}
    assert "private provider credential" not in str(failure_logs)
    assert returned_failure_result.status == "failed"
    assert returned_failure_result.progress == 60
    assert returned_failure_result.error == TASK_EXECUTION_ERROR


@pytest.mark.anyio
@pytest.mark.parametrize("override", [{"unexpected": "secret"}, ["not-a-dict"]])
async def test_invalid_override_is_rejected_without_creating_history(
    session_factory: SessionFactory,
    override: object,
) -> None:
    registry = TaskRegistry()
    registry.register(PartialTask)
    runner, runs = make_runner(
        session_factory, registry, settings_for((PartialTask.name, TaskSettings()))
    )

    with pytest.raises(ValueError, match="Invalid task parameters"):
        await runner.start(
            PartialTask.name,
            "manual",
            override,  # type: ignore[arg-type]
        )

    assert runs.list_runs() == []


def test_task_logs_reject_non_finite_json_context(
    session_factory: SessionFactory,
) -> None:
    runs = TaskRunRepository(session_factory)
    run = runs.create_run("logs", "manual")
    context = TaskContext(
        run_id=run.id,
        settings=settings_for(),
        resources=RuntimeResources(
            instrument_repository=object(), bar_repository=object()
        ),
        runs=runs,
    )

    with pytest.raises(ValueError):
        context.log("INFO", "invalid", {"value": float("nan")})

    assert runs.list_logs(run.id) == []


def test_stale_queued_and_running_rows_are_interrupted_at_runner_startup(
    session_factory: SessionFactory,
) -> None:
    registry = TaskRegistry()
    runs = TaskRunRepository(session_factory)
    stale = runs.create_run("old", "scheduled", status="running")
    queued = runs.create_run("queued", "scheduled")

    make_runner(
        session_factory, registry, default_settings().model_copy(update={"tasks": {}})
    )

    assert runs.get_run(stale.id).status == "interrupted"
    assert runs.get_run(stale.id).finished_at is not None
    assert runs.get_run(queued.id).status == "interrupted"
    assert runs.get_run(queued.id).finished_at is not None


@pytest.mark.anyio
async def test_scheduled_itiger_task_uses_configured_token_without_persisting_it(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
) -> None:
    token = "secret-configured-token"
    settings = settings_for(
        (
            SyncUniversesTask.name,
            TaskSettings(
                params={"universe_codes": ["hstech"], "itiger_token": token}
            ),
        )
    )
    expected = UniverseSnapshot(
        universe_code="hstech",
        source="itiger",
        effective_date=None,
        members=(instrument_dto("0700.HK"),),
    )
    calls: list[str] = []

    def fake_fetch(**kwargs: object) -> UniverseSnapshot:
        calls.append(str(kwargs["bearer_token"]))
        return expected

    monkeypatch.setattr(
        "app.providers.hstech_api.fetch_hstech_api_snapshot", fake_fetch
    )
    registry = TaskRegistry()
    registry.register(SyncUniversesTask)
    provider_registry = ProviderRegistry(
        settings=settings,
        universe_providers={
            "hstech": ItigerUniverseProvider(bearer_token="initial-token")
        },
    )
    resources = RuntimeResources(
        instrument_repository=InstrumentRepository(session_factory),
        bar_repository=BarRepository(session_factory),
        provider_registry=provider_registry,
    )
    runs = TaskRunRepository(session_factory)
    runner = TaskRunner(registry, runs, settings, resources)

    run = await runner.start(SyncUniversesTask.name, "scheduled")
    await runner.wait_for_idle()

    assert calls == [token]
    assert "itiger_token" not in run.params
    assert "itiger_token" not in run.config_snapshot["params"]
    persisted = runs.get_run(run.id)
    assert persisted is not None
    assert "itiger_token" not in persisted.params
    assert token not in str(persisted.params)
    assert token not in str(persisted.config_snapshot)


@pytest.mark.anyio
async def test_history_purge_uses_retention_and_cascades_logs(
    session_factory: SessionFactory,
) -> None:
    registry = TaskRegistry()
    registry.register(PurgeHistoryTask)
    settings = settings_for((PurgeHistoryTask.name, TaskSettings()))
    runner, runs = make_runner(session_factory, registry, settings)
    old = runs.create_run(
        "old",
        "scheduled",
        status="success",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    runs.create_log(old.id, "INFO", "old log")
    recent = runs.create_run("recent", "manual", status="success")
    old_queued = runs.create_run(
        "old.queued",
        "scheduled",
        status="queued",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    old_running = runs.create_run(
        "old.running",
        "scheduled",
        status="running",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    runs.create_log(old_running.id, "INFO", "still running")

    purge = await runner.start(PurgeHistoryTask.name, "manual", {"retention_days": 30})
    result = await wait_for_run(runner, runs, purge.id)

    assert result.status == "success"
    assert runs.get_run(old.id) is None
    assert runs.list_logs(old.id) == []
    assert runs.get_run(recent.id) is not None
    assert runs.get_run(old_queued.id).status == "queued"
    assert runs.get_run(old_running.id).status == "running"

    progressed = runs.update_run(old_running.id, progress=65)
    runs.create_log(old_running.id, "INFO", "progress after purge")
    assert progressed.progress == 65
    assert [log.message for log in runs.list_logs(old_running.id)] == [
        "still running",
        "progress after purge",
    ]
    assert any(log.message == "Task history purged" for log in runs.list_logs(purge.id))
