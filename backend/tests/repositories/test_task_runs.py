"""Task run and structured log persistence tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.database import SessionFactory
from app.repositories.task_runs import TaskRunNotFoundError, TaskRunRepository


def test_task_run_and_log_crud(session_factory: SessionFactory) -> None:
    repository = TaskRunRepository(session_factory)
    created = repository.create_run(
        "market.sync_us_daily",
        "manual",
        params={"symbols": ["AAA"]},
        config_snapshot={"revision": 3},
    )

    assert created.status == "queued"
    assert created.progress == 0.0
    assert repository.get_run(created.id) == created
    assert repository.list_runs("market.sync_us_daily") == [created]

    started_at = datetime(2025, 1, 2, 3, 4, tzinfo=UTC)
    running = repository.update_run(
        created.id, status="running", progress=25.0, started_at=started_at
    )
    assert running.status == "running"
    assert running.started_at == started_at
    finished = repository.update_run(
        created.id,
        status="success",
        progress=100.0,
        error=None,
        finished_at=started_at + timedelta(minutes=2),
    )
    assert finished.status == "success"
    assert finished.progress == 100.0

    log = repository.create_log(
        created.id,
        "INFO",
        "started",
        context={"symbol": "AAA"},
        created_at=started_at,
    )
    assert repository.get_log(log.id) == log
    assert repository.list_logs(created.id) == [log]
    updated_log = repository.update_log(
        log.id, message="completed", context={"succeeded": 1}
    )
    assert updated_log.message == "completed"
    assert updated_log.context == {"succeeded": 1}
    assert repository.delete_log(log.id) is True
    assert repository.get_log(log.id) is None

    assert repository.delete_run(created.id) is True
    assert repository.get_run(created.id) is None
    assert repository.delete_run(created.id) is False


def test_stale_interruption_and_retention_delete_are_explicit(
    session_factory: SessionFactory,
) -> None:
    repository = TaskRunRepository(session_factory)
    old_time = datetime(2024, 1, 1, tzinfo=UTC)
    recent_time = datetime(2025, 1, 1, tzinfo=UTC)
    old = repository.create_run(
        "old", "scheduled", status="running", created_at=old_time
    )
    succeeded = repository.create_run(
        "done", "scheduled", status="success", created_at=old_time
    )
    recent = repository.create_run("recent", "manual", created_at=recent_time)

    assert repository.mark_stale_interrupted() == 2
    assert repository.get_run(old.id).status == "interrupted"
    assert repository.get_run(recent.id).status == "interrupted"
    assert repository.get_run(recent.id).finished_at is not None
    assert repository.get_run(succeeded.id).status == "success"

    repository.create_log(old.id, "ERROR", "interrupted")
    assert repository.delete_before(datetime(2024, 6, 1, tzinfo=UTC)) == 2
    assert repository.list_logs(old.id) == []
    assert repository.get_run(recent.id) is not None

    with pytest.raises(TaskRunNotFoundError):
        repository.update_run(999999, status="failed", error="missing")


def test_retention_preserves_active_runs_and_deletes_every_terminal_status(
    session_factory: SessionFactory,
) -> None:
    repository = TaskRunRepository(session_factory)
    old_time = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = datetime(2024, 6, 1, tzinfo=UTC)
    active = [
        repository.create_run("active", "manual", status=status, created_at=old_time)
        for status in ("queued", "running")
    ]
    terminal = [
        repository.create_run("terminal", "scheduled", status=status, created_at=old_time)
        for status in ("success", "partial", "failed", "skipped", "interrupted")
    ]
    for run in (*active, *terminal):
        repository.create_log(run.id, "INFO", "retention fixture")

    assert repository.delete_before(cutoff) == len(terminal)
    assert all(repository.get_run(run.id) is None for run in terminal)
    assert [repository.get_run(run.id).status for run in active] == [
        "queued",
        "running",
    ]
    assert all(len(repository.list_logs(run.id)) == 1 for run in active)
