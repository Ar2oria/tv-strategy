"""Production application composition, startup recovery, and lifecycle tests."""

import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.config.defaults import PURGE_TASK_HISTORY, default_settings
from app.config.models import TaskSettings
from app.config.store import ConfigService
from app.db.database import SessionFactory
from app.indicators.registry import IndicatorRegistry
from app.main import UVICORN_WORKERS, AppSettings, create_app
from app.providers.registry import ProviderRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.repositories.task_runs import TaskRunRepository
from app.services.bar_sync_service import BarSyncService
from app.services.cron_scheduler import JOB_ID_PREFIX, CronScheduler
from app.services.task_runner import TaskRunner
from app.tasks.registry import TaskRegistry
from fastapi.testclient import TestClient

from tests.conftest import upgrade_database


def application_settings(tmp_path: Path, **overrides: object) -> AppSettings:
    values = {
        "config_path": tmp_path / "settings.json",
        "database_path": tmp_path / "application.sqlite3",
        "allowed_hosts": AppSettings().allowed_hosts + ("testserver",),
        "read_rate_limit": 1_000,
        "write_rate_limit": 1_000,
        "compute_rate_limit": 1_000,
        "shutdown_timeout_seconds": 1.0,
    }
    return AppSettings(**{**values, **overrides})


def test_local_server_defaults_are_explicit_and_hot_settings_are_separate() -> None:
    settings = AppSettings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.workers == UVICORN_WORKERS == 1
    assert settings.config_path.is_absolute()
    assert settings.database_path.is_absolute()
    assert settings.config_path.name == "settings.json"
    assert settings.database_path.name == "backend.sqlite3"
    assert not hasattr(settings, "markets")
    assert not hasattr(settings, "tasks")


def test_package_metadata_requires_the_approved_python_stack() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as stream:
        metadata = tomllib.load(stream)

    assert metadata["project"]["requires-python"] == ">=3.12"


def test_startup_discovers_recovers_and_adds_only_registered_task_defaults(
    tmp_path: Path,
) -> None:
    settings = application_settings(tmp_path)
    upgrade_database(settings.database_path)
    seed_sessions = SessionFactory(settings.database_path)
    stale_runs = TaskRunRepository(seed_sessions)
    running = stale_runs.create_run("old.running", "manual", status="running")
    queued = stale_runs.create_run("old.queued", "scheduled", status="queued")
    seed_sessions.dispose()

    config = ConfigService(settings.config_path)
    config.update(
        0,
        lambda old: old.model_copy(
            update={
                "tasks": {
                    "unregistered.retained": TaskSettings(
                        enabled=False,
                        cron="15 4 * * 2",
                        params={"preserve": True},
                    )
                }
            }
        ),
    )
    revision_before_startup = config.get().revision
    app = create_app(settings)

    with TestClient(app):
        container = app.state.container
        current = container.config_service.get()

        assert isinstance(container.indicator_registry, IndicatorRegistry)
        assert isinstance(container.task_registry, TaskRegistry)
        assert {item.name for item in container.indicator_registry.descriptors} >= {
            "donchian",
            "rsi",
        }
        assert {item.name for item in container.task_registry.descriptors} == set(
            default_settings().tasks
        )
        assert isinstance(container.instrument_repository, InstrumentRepository)
        assert isinstance(container.bar_repository, BarRepository)
        assert isinstance(container.task_run_repository, TaskRunRepository)
        assert isinstance(container.task_runner, TaskRunner)
        assert isinstance(container.cron_scheduler, CronScheduler)
        assert container.config is container.config_service
        assert container.runner is container.task_runner
        assert container.scheduler is container.cron_scheduler

        assert current.revision == revision_before_startup + 1
        assert set(current.tasks) == set(default_settings().tasks) | {
            "unregistered.retained"
        }
        assert current.tasks[PURGE_TASK_HISTORY] == TaskSettings(enabled=False)
        assert current.tasks["unregistered.retained"].params == {"preserve": True}
        assert container.cron_scheduler.scheduler.get_jobs() == []

        assert container.task_run_repository.get_run(running.id).status == "interrupted"
        assert container.task_run_repository.get_run(queued.id).status == "interrupted"
        assert isinstance(container.resources.provider_registry, ProviderRegistry)
        assert isinstance(container.resources.bar_sync_service, BarSyncService)

    assert not container.cron_scheduler.scheduler.running


def test_startup_schedules_enabled_registered_tasks_without_downtime_replay(
    tmp_path: Path,
) -> None:
    settings = application_settings(tmp_path)
    config = ConfigService(settings.config_path)
    config.update(
        0,
        lambda old: old.model_copy(
            update={
                "tasks": {
                    PURGE_TASK_HISTORY: TaskSettings(
                        enabled=True,
                        cron="0 9 * * 0",
                    ),
                    "unregistered.disabled": TaskSettings(enabled=False),
                }
            }
        ),
    )
    app = create_app(settings)
    started_at = datetime.now(UTC)

    with TestClient(app):
        scheduler = app.state.container.cron_scheduler.scheduler
        jobs = scheduler.get_jobs()
        assert scheduler.running
        assert [job.id for job in jobs] == [f"{JOB_ID_PREFIX}{PURGE_TASK_HISTORY}"]
        assert jobs[0].trigger.run_date > started_at
        assert jobs[0].args == (PURGE_TASK_HISTORY, "0 9 * * 0", "UTC")

    assert not scheduler.running


def test_shutdown_waits_only_up_to_the_configured_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def stuck_close(self: TaskRunner) -> None:
        import asyncio

        await asyncio.sleep(60)

    monkeypatch.setattr(TaskRunner, "aclose", stuck_close)
    app = create_app(application_settings(tmp_path, shutdown_timeout_seconds=0.01))
    started = time.monotonic()

    with TestClient(app):
        pass

    assert time.monotonic() - started < 2
    assert "Timed out waiting for TaskRunner shutdown" in caplog.text
    assert not app.state.container.cron_scheduler.scheduler.running
