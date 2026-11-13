"""Isolated Task management API tests with persistent runs and logs."""

import time
from datetime import UTC, datetime, timedelta
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.responses import register_response_handlers
from app.api.tasks import router as tasks_router
from app.config.defaults import default_settings
from app.config.models import TaskSettings
from app.config.store import ConfigService
from app.db.database import SessionFactory
from app.repositories.task_runs import TaskRunRepository
from app.services.resources import RuntimeResources
from app.services.task_runner import TaskRunner
from app.services.task_service import TaskService
from app.tasks.base import Task, TaskContext, TaskParams, TaskResult
from app.tasks.builtin.purge_history import PurgeHistoryTask
from app.tasks.builtin.sync_universes import SyncUniversesTask, UniverseSyncParams
from app.tasks.registry import TaskRegistry

API_ROOT = "/api/v1"
TERMINAL_STATUSES = {"success", "partial", "failed", "skipped", "interrupted"}


class APIParams(TaskParams):
    value: int = 1


class APITask(Task):
    name: ClassVar[str] = "test.api"
    display_name: ClassVar[str] = "API task"
    description: ClassVar[str] = "Exercises the Task API"
    params_model: ClassVar[type[BaseModel]] = APIParams

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        assert isinstance(params, APIParams)
        context.log("INFO", "API task completed", value=params.value)
        return TaskResult(status="partial", progress=75, error="fixture partial")


@pytest.fixture
def api(
    session_factory: SessionFactory, tmp_path: Path
) -> Iterator[tuple[TestClient, ConfigService]]:
    registry = TaskRegistry()
    registry.register(PurgeHistoryTask)
    registry.register(APITask)
    registry.register(SyncUniversesTask)
    config = ConfigService(tmp_path / "settings.json")
    config.update(
        0,
        lambda old: old.model_copy(
            update={"tasks": {**old.tasks, APITask.name: TaskSettings()}}
        ),
    )
    runs = TaskRunRepository(session_factory)
    resources = RuntimeResources(
        instrument_repository=object(), bar_repository=object()
    )
    runner = TaskRunner(registry, runs, config, resources)
    service = TaskService(config, registry, runs, runner)
    app = FastAPI()
    app.state.task_service = service
    app.include_router(tasks_router)
    register_response_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, config
    finally:
        client.close()


def test_list_get_and_revision_checked_config_update(
    api: tuple[TestClient, ConfigService],
) -> None:
    client, config = api

    listed = client.get(f"{API_ROOT}/tasks")
    current = client.get(f"{API_ROOT}/tasks/{APITask.name}/config")
    revision = current.json()["data"]["revision"]
    updated = client.put(
        f"{API_ROOT}/tasks/{APITask.name}/config",
        json={
            "expected_revision": revision,
            "enabled": True,
            "cron": "0 9 * * 0",
            "params": {"value": 4},
        },
    )
    conflict = client.put(
        f"{API_ROOT}/tasks/{APITask.name}/config",
        json={"expected_revision": revision, "enabled": False},
    )

    assert listed.status_code == 200
    assert {item["name"] for item in listed.json()["data"]} == {
        APITask.name,
        PurgeHistoryTask.name,
        SyncUniversesTask.name,
    }
    assert listed.json()["meta"]["count"] == 3
    assert current.status_code == 200
    assert (
        current.json()["data"]["params_schema"]["properties"]["value"]["default"] == 1
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["revision"] == revision + 1
    assert updated.json()["data"]["enabled"] is True
    assert updated.json()["data"]["cron"] == "0 9 * * 0"
    assert config.get().tasks[APITask.name].params == {"value": 4}
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "config_conflict"
    assert set(updated.json()) == {"success", "data", "error", "meta"}


def test_immediate_run_history_and_logs_use_consistent_envelopes(
    api: tuple[TestClient, ConfigService],
) -> None:
    client, _ = api

    started = client.post(
        f"{API_ROOT}/tasks/{APITask.name}/runs", json={"params": {"value": 9}}
    )
    assert started.status_code == 202
    run_id = started.json()["data"]["id"]
    deadline = time.monotonic() + 2
    history_payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        history = client.get(f"{API_ROOT}/tasks/{APITask.name}/runs")
        history_payload = history.json()
        if history_payload["data"][0]["status"] in TERMINAL_STATUSES:
            break
        time.sleep(0.01)
    logs = client.get(f"{API_ROOT}/task-runs/{run_id}/logs")

    assert started.json()["data"]["params"] == {"value": 9}
    assert history_payload["data"][0]["status"] == "partial"
    assert history_payload["data"][0]["progress"] == 75
    assert history_payload["meta"]["task_name"] == APITask.name
    assert logs.status_code == 200
    assert logs.json()["data"][0]["message"] == "API task completed"
    assert logs.json()["data"][0]["context"] == {"value": 9}
    assert logs.json()["meta"]["run_id"] == run_id


def test_immediate_run_accepts_empty_body_and_list_serializes_last_run(
    api: tuple[TestClient, ConfigService],
) -> None:
    client, _ = api

    started = client.post(f"{API_ROOT}/tasks/{APITask.name}/runs")

    assert started.status_code == 202
    run_id = started.json()["data"]["id"]
    deadline = time.monotonic() + 2
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = client.get(f"{API_ROOT}/tasks/{APITask.name}/runs").json()["data"][0]
        if latest["status"] in TERMINAL_STATUSES:
            break
        time.sleep(0.01)
    listed = client.get(f"{API_ROOT}/tasks")

    assert latest["status"] == "partial"
    assert latest["id"] == run_id
    assert listed.status_code == 200
    api_task = next(
        item for item in listed.json()["data"] if item["name"] == APITask.name
    )
    assert api_task["last_run"]["id"] == run_id


def test_run_and_log_pages_include_totals_and_latest_first_ordering(
    api: tuple[TestClient, ConfigService],
) -> None:
    client, _ = api
    repository = client.app.state.task_service._runs
    created = [
        repository.create_run(
            APITask.name,
            "manual",
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
        )
        for index in range(25)
    ]
    selected = created[0]
    for index in range(25):
        repository.create_log(
            selected.id,
            "INFO",
            f"log-{index}",
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index),
        )

    first_runs = client.get(f"{API_ROOT}/tasks/{APITask.name}/runs?limit=20&offset=0")
    second_runs = client.get(f"{API_ROOT}/tasks/{APITask.name}/runs?limit=20&offset=20")
    first_logs = client.get(
        f"{API_ROOT}/task-runs/{selected.id}/logs?limit=20&offset=0&order=desc"
    )
    second_logs = client.get(
        f"{API_ROOT}/task-runs/{selected.id}/logs?limit=20&offset=20&order=desc"
    )

    assert [run["id"] for run in first_runs.json()["data"]] == list(range(25, 5, -1))
    assert [run["id"] for run in second_runs.json()["data"]] == [5, 4, 3, 2, 1]
    assert first_runs.json()["meta"]["total"] == 25
    assert second_runs.json()["meta"]["total"] == 25
    assert [log["message"] for log in first_logs.json()["data"]] == [
        f"log-{index}" for index in range(24, 4, -1)
    ]
    assert [log["message"] for log in second_logs.json()["data"]] == [
        f"log-{index}" for index in range(4, -1, -1)
    ]
    assert first_logs.json()["meta"]["total"] == 25
    assert second_logs.json()["meta"]["total"] == 25


def test_itiger_token_is_persisted_in_task_configuration(
    api: tuple[TestClient, ConfigService],
) -> None:
    client, config = api
    revision = config.get().revision

    response = client.put(
        f"{API_ROOT}/tasks/{SyncUniversesTask.name}/config",
        json={
            "expected_revision": revision,
            "params": {"universe_codes": [], "itiger_token": "configured-token"},
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["params"]["itiger_token"] == "********"
    assert (
        config.get().tasks[SyncUniversesTask.name].params["itiger_token"]
        == "configured-token"
    )
    description = UniverseSyncParams.model_json_schema()["properties"]["itiger_token"][
        "description"
    ]
    assert "保存到配置文件" in description
    assert "不会保存到配置" not in description


def test_masked_itiger_token_preserves_the_saved_secret_on_task_update(
    api: tuple[TestClient, ConfigService],
) -> None:
    client, config = api
    first = client.put(
        f"{API_ROOT}/tasks/{SyncUniversesTask.name}/config",
        json={
            "expected_revision": config.get().revision,
            "params": {"universe_codes": [], "itiger_token": "configured-token"},
        },
    )
    assert first.status_code == 200

    second = client.put(
        f"{API_ROOT}/tasks/{SyncUniversesTask.name}/config",
        json={
            "expected_revision": config.get().revision,
            "params": {"universe_codes": ["hstech"], "itiger_token": "********"},
        },
    )

    assert second.status_code == 200
    assert second.json()["data"]["params"]["itiger_token"] == "********"
    assert (
        config.get().tasks[SyncUniversesTask.name].params["itiger_token"]
        == "configured-token"
    )
    assert "configured-token" not in client.get(f"{API_ROOT}/tasks").text


def test_invalid_configs_params_and_missing_resources_are_sanitized(
    api: tuple[TestClient, ConfigService],
) -> None:
    client, config = api
    revision = config.get().revision

    bad_cron = client.put(
        f"{API_ROOT}/tasks/{APITask.name}/config",
        json={"expected_revision": revision, "cron": "0 0 * * * *"},
    )
    bad_params = client.post(
        f"{API_ROOT}/tasks/{APITask.name}/runs",
        json={"params": {"unexpected": "private value"}},
    )
    missing_task = client.get(f"{API_ROOT}/tasks/missing/runs")
    missing_run = client.get(f"{API_ROOT}/task-runs/999999/logs")
    extra = client.post(
        f"{API_ROOT}/tasks/{APITask.name}/runs", json={"unexpected": True}
    )

    assert bad_cron.status_code == 422
    assert bad_cron.json()["error"]["code"] == "invalid_task_config"
    assert bad_params.status_code == 422
    assert bad_params.json()["error"] == {
        "code": "invalid_task_params",
        "message": "Invalid task parameters",
    }
    assert "private value" not in bad_params.text
    assert missing_task.status_code == 404
    assert missing_run.status_code == 404
    assert extra.status_code == 422
    assert config.get().revision == revision
    for response in (bad_cron, bad_params, missing_task, missing_run, extra):
        assert set(response.json()) == {"success", "data", "error", "meta"}
        assert "Traceback" not in response.text
