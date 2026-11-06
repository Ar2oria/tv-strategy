"""Versioned full-document settings API and hot-apply integration tests."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from app.config.defaults import PURGE_TASK_HISTORY
from app.config.models import Settings, TaskSettings
from app.config.store import ConfigService
from app.main import AppSettings, create_app
from app.services.cron_scheduler import CronScheduler
from fastapi.testclient import TestClient

API_ROOT = "/api/v1"


def application_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        config_path=tmp_path / "settings.json",
        database_path=tmp_path / "settings-api.sqlite3",
        allowed_hosts=AppSettings().allowed_hosts + ("testserver",),
        read_rate_limit=1_000,
        write_rate_limit=1_000,
        compute_rate_limit=1_000,
    )


def update_payload(settings: Settings) -> dict[str, Any]:
    document = settings.model_dump(mode="json")
    revision = document.pop("revision")
    return {**document, "expected_revision": revision}


def assert_error_envelope(response: object, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    payload = response.json()
    assert set(payload) == {"success", "data", "error", "meta"}
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == code
    assert "Traceback" not in response.text


def enable_purge_task(path: Path) -> None:
    config = ConfigService(path)
    config.update(
        0,
        lambda old: old.model_copy(
            update={
                "tasks": {
                    **old.tasks,
                    PURGE_TASK_HISTORY: TaskSettings(
                        enabled=True,
                        cron="0 9 * * 0",
                    ),
                }
            }
        ),
    )


def scheduler_snapshot(scheduler: CronScheduler) -> list[tuple[object, ...]]:
    return sorted(
        (job.id, tuple(job.args), job.trigger.run_date)
        for job in scheduler.scheduler.get_jobs()
        if job.id.startswith("task-cron:")
    )


def test_get_and_put_replace_the_full_document_and_hot_apply_without_restart(
    tmp_path: Path,
) -> None:
    settings = application_settings(tmp_path)
    enable_purge_task(settings.config_path)
    app = create_app(settings)

    with TestClient(app) as client:
        container = app.state.container
        original_runner = container.task_runner
        original_scheduler = container.cron_scheduler
        original_indicator_service = app.state.indicator_service

        fetched = client.get(f"{API_ROOT}/settings")
        assert fetched.status_code == 200
        assert set(fetched.json()) == {"success", "data", "error", "meta"}
        assert fetched.json()["data"] == container.config_service.get().model_dump(
            mode="json"
        )
        assert fetched.json()["data"]["revision"] == 1

        candidate = update_payload(container.config_service.get())
        candidate["timezone"] = "Asia/Shanghai"
        candidate["markets"]["a_share"]["provider"] = "baostock"
        candidate["indicators"]["max_active_indicators"] = 7
        updated = client.put(f"{API_ROOT}/settings", json=candidate)

        assert updated.status_code == 200
        assert updated.json()["data"]["revision"] == 2
        assert updated.json()["data"]["timezone"] == "Asia/Shanghai"
        assert updated.json()["data"]["markets"]["a_share"]["provider"] == "baostock"
        assert updated.json()["data"]["indicators"]["max_active_indicators"] == 7
        assert (
            json.loads(settings.config_path.read_text(encoding="utf-8"))
            == updated.json()["data"]
        )

        assert app.state.container is container
        assert container.task_runner is original_runner
        assert container.cron_scheduler is original_scheduler
        assert original_scheduler.scheduler.running
        assert scheduler_snapshot(original_scheduler)[0][1] == (
            PURGE_TASK_HISTORY,
            "0 9 * * 0",
            "Asia/Shanghai",
        )
        assert container.provider_settings["a_share"].provider == "baostock"
        assert container.indicator_service is app.state.indicator_service
        assert app.state.indicator_service is not original_indicator_service
        assert client.get(f"{API_ROOT}/settings").json()["data"]["revision"] == 2


def test_two_concurrent_writers_have_one_success_and_one_revision_conflict(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app) as client:
        current = client.get(f"{API_ROOT}/settings").json()["data"]
        payload = update_payload(Settings.model_validate(current))
        payload["timezone"] = "Europe/London"
        barrier = Barrier(2)

        def put() -> tuple[int, str]:
            barrier.wait(timeout=2)
            response = client.put(f"{API_ROOT}/settings", json=payload)
            return response.status_code, (
                response.json()["error"]["code"] if response.json()["error"] else ""
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: put(), range(2)))

        assert sorted(status for status, _ in outcomes) == [200, 409]
        assert [code for status, code in outcomes if status == 409] == [
            "config_conflict"
        ]
        assert app.state.container.config_service.get().revision == 1
        assert client.get(f"{API_ROOT}/settings").json()["data"]["revision"] == 1


def test_invalid_and_stale_settings_never_change_the_document(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app) as client:
        original = app.state.container.config_service.get()
        original_bytes = app.state.app_settings.config_path.read_bytes()

        missing_document = client.put(
            f"{API_ROOT}/settings", json={"expected_revision": 0}
        )
        bad_provider_document = update_payload(original)
        bad_provider_document["markets"]["a_share"]["provider"] = "private-provider"
        bad_provider = client.put(f"{API_ROOT}/settings", json=bad_provider_document)
        bad_timezone_document = update_payload(original)
        bad_timezone_document["timezone"] = "Not/A_Real_Zone"
        bad_timezone = client.put(f"{API_ROOT}/settings", json=bad_timezone_document)
        extra_document = update_payload(original)
        extra_document["unexpected"] = "private input"
        extra = client.put(f"{API_ROOT}/settings", json=extra_document)
        stale_document = update_payload(original)
        stale_document["expected_revision"] = 999
        stale = client.put(f"{API_ROOT}/settings", json=stale_document)

        assert_error_envelope(missing_document, 422, "validation_error")
        assert_error_envelope(bad_provider, 422, "invalid_configuration")
        assert_error_envelope(bad_timezone, 422, "invalid_configuration")
        assert_error_envelope(extra, 422, "validation_error")
        assert_error_envelope(stale, 409, "config_conflict")
        assert "private-provider" not in bad_provider.text
        assert "private input" not in extra.text
        assert app.state.container.config_service.get() == original
        assert app.state.app_settings.config_path.read_bytes() == original_bytes


def test_listener_failure_restores_file_provider_indicator_and_scheduler_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = application_settings(tmp_path)
    enable_purge_task(settings.config_path)
    original_apply = CronScheduler.apply_settings
    failed_candidates: list[int] = []

    def fail_once_for_candidate(scheduler: CronScheduler, candidate: Settings) -> None:
        if candidate.timezone == "Asia/Tokyo" and not failed_candidates:
            failed_candidates.append(candidate.revision)
            raise RuntimeError("private scheduler listener secret")
        original_apply(scheduler, candidate)

    monkeypatch.setattr(CronScheduler, "apply_settings", fail_once_for_candidate)
    app = create_app(settings)

    with TestClient(app) as client:
        container = app.state.container
        before = container.config_service.get()
        before_bytes = settings.config_path.read_bytes()
        before_jobs = scheduler_snapshot(container.cron_scheduler)
        before_provider = container.provider_settings
        candidate = update_payload(before)
        candidate["timezone"] = "Asia/Tokyo"
        candidate["markets"]["a_share"]["provider"] = "baostock"
        candidate["indicators"]["max_active_indicators"] = 12

        response = client.put(f"{API_ROOT}/settings", json=candidate)

        assert_error_envelope(response, 500, "configuration_apply_failed")
        assert "private scheduler listener secret" not in response.text
        assert settings.config_path.read_bytes() == before_bytes
        assert container.config_service.get() == before
        assert container.provider_settings == before_provider
        assert container.indicator_settings == before.indicators
        assert app.state.indicator_service is container.indicator_service
        assert scheduler_snapshot(container.cron_scheduler) == before_jobs
        assert failed_candidates == [before.revision + 1]
