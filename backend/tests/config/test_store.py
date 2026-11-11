"""Behavioral tests for hot JSON configuration persistence."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.models import Settings, TaskSettings
from app.config.store import (
    ConfigApplyError,
    ConfigConflictError,
    ConfigService,
    ConfigValidationError,
)

CLEANUP_TASK = "system.purge_task_history"
TEMP_FILE_PATTERN = ".settings.json.*.tmp"
DEFAULT_SPOT_PAIRS = [
    {"exchange": "binance", "symbol": "BTC/USDT"},
    {"exchange": "binance", "symbol": "ETH/USDT"},
]


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


@pytest.fixture
def service(config_path: Path) -> ConfigService:
    return ConfigService(config_path)


def update_cleanup(settings: Settings, **changes: object) -> Settings:
    """Return settings with a new cleanup task and no in-place changes."""
    cleanup = settings.tasks[CLEANUP_TASK].model_copy(update=changes)
    return settings.model_copy(
        update={"tasks": {**settings.tasks, CLEANUP_TASK: cleanup}}
    )


def enable_cleanup(settings: Settings) -> Settings:
    return update_cleanup(settings, enabled=True)


def update_schedule(
    settings: Settings,
    field: str,
    value: str,
) -> Settings:
    if field == "timezone":
        return settings.model_copy(update={"timezone": value})
    return update_cleanup(settings, **{field: value})


def assert_temp_files_absent(config_path: Path) -> None:
    assert list(config_path.parent.glob(TEMP_FILE_PATTERN)) == []


def test_defaults_are_structured_and_cleanup_is_disabled(
    service: ConfigService,
) -> None:
    settings = service.get()

    assert settings.schema_version == 1
    assert settings.revision == 0
    assert settings.timezone == "UTC"
    assert settings.tasks["market.sync_crypto_daily"].params["spot_pairs"] == DEFAULT_SPOT_PAIRS
    assert all("symbols" not in market.model_fields_set for market in settings.markets.values())
    assert settings.tasks[CLEANUP_TASK].enabled is False


def test_models_are_frozen_and_forbid_extra_fields(
    service: ConfigService,
) -> None:
    settings = service.get()

    with pytest.raises(ValidationError):
        settings.revision = 2

    with pytest.raises(ValidationError):
        Settings.model_validate(
            {**settings.model_dump(mode="python"), "unexpected": True}
        )


def test_returned_models_cannot_mutate_stored_state(
    service: ConfigService,
) -> None:
    returned = service.get()
    returned.tasks["market.sync_crypto_daily"].params["spot_pairs"].append(
        {"exchange": "okx", "symbol": "SOL/USDT"}
    )
    returned.tasks[CLEANUP_TASK] = TaskSettings(enabled=True)

    stored = service.get()
    assert stored.tasks["market.sync_crypto_daily"].params["spot_pairs"] == DEFAULT_SPOT_PAIRS
    assert stored.tasks[CLEANUP_TASK].enabled is False


def test_valid_update_increments_revision_once_and_persists(
    service: ConfigService,
    config_path: Path,
) -> None:
    previous = service.get()

    updated = service.update(
        expected_revision=previous.revision,
        build_next=enable_cleanup,
    )

    assert previous.revision == 0
    assert updated.revision == 1
    assert updated.tasks[CLEANUP_TASK].enabled is True
    assert service.get() == updated
    assert json.loads(config_path.read_text(encoding="utf-8"))["revision"] == 1
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert all("symbols" not in market for market in persisted["markets"].values())
    assert ConfigService(config_path).get() == updated
    assert_temp_files_absent(config_path)


def test_stale_revision_raises_conflict(service: ConfigService) -> None:
    before = service.get()

    with pytest.raises(ConfigConflictError):
        service.update(
            expected_revision=service.get().revision - 1,
            build_next=lambda old: old,
        )

    assert service.get() == before


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("timezone", "Mars/Olympus_Mons"),
        ("cron", "not a cron expression"),
    ],
)
def test_invalid_timezone_or_cron_raises_validation_error(
    service: ConfigService,
    config_path: Path,
    field: str,
    invalid_value: str,
) -> None:
    before = service.get()
    original_document = config_path.read_bytes()

    with pytest.raises(ConfigValidationError):
        service.update(
            expected_revision=before.revision,
            build_next=lambda old: update_schedule(
                old, field, invalid_value
            ),
        )

    assert service.get() == before
    assert config_path.read_bytes() == original_document
    assert_temp_files_absent(config_path)


def test_custom_validator_runs_before_persistence(
    service: ConfigService,
    config_path: Path,
) -> None:
    original_document = config_path.read_bytes()

    def reject_update(candidate: Settings) -> None:
        assert candidate.revision == 1
        assert json.loads(config_path.read_text(encoding="utf-8"))["revision"] == 0
        raise ValueError("rejected by custom validator")

    service.add_validator(reject_update)

    with pytest.raises(ConfigValidationError) as failure:
        service.update(expected_revision=0, build_next=enable_cleanup)

    assert isinstance(failure.value.__cause__, ValueError)
    assert service.get().revision == 0
    assert config_path.read_bytes() == original_document
    assert_temp_files_absent(config_path)


def test_listener_runs_after_persistence_and_receives_a_copy(
    service: ConfigService,
    config_path: Path,
) -> None:
    observed: list[tuple[int, int]] = []

    def listener(candidate: Settings) -> None:
        persisted_revision = json.loads(
            config_path.read_text(encoding="utf-8")
        )["revision"]
        observed.append((candidate.revision, persisted_revision))
        candidate.tasks["market.sync_crypto_daily"].params["spot_pairs"].clear()

    service.subscribe(listener)
    updated = service.update(expected_revision=0, build_next=enable_cleanup)

    assert observed == [(1, 1)]
    assert updated.tasks["market.sync_crypto_daily"].params["spot_pairs"] == DEFAULT_SPOT_PAIRS
    assert service.get().tasks["market.sync_crypto_daily"].params["spot_pairs"] == DEFAULT_SPOT_PAIRS


def test_listener_failure_restores_file_runtime_and_listeners(
    service: ConfigService,
    config_path: Path,
) -> None:
    original_document = config_path.read_bytes()
    observed_revisions: list[int] = []

    def failing_listener(candidate: Settings) -> None:
        observed_revisions.append(candidate.revision)
        if candidate.revision == 1:
            raise RuntimeError("simulated listener failure")

    service.subscribe(failing_listener)

    with pytest.raises(ConfigApplyError) as failure:
        service.update(expected_revision=0, build_next=enable_cleanup)

    assert isinstance(failure.value.__cause__, RuntimeError)
    assert "simulated listener failure" in str(failure.value)
    assert service.get().revision == 0
    assert service.get().tasks[CLEANUP_TASK].enabled is False
    assert config_path.read_bytes() == original_document
    assert observed_revisions == [1, 0]
    assert_temp_files_absent(config_path)


def test_write_failure_preserves_state_and_removes_temp_files(
    service: ConfigService,
    config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_document = config_path.read_bytes()

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr("app.config.store.os.replace", fail_replace)

    with pytest.raises(ConfigApplyError) as failure:
        service.update(expected_revision=0, build_next=enable_cleanup)

    assert isinstance(failure.value.__cause__, OSError)
    assert service.get().revision == 0
    assert config_path.read_bytes() == original_document
    assert_temp_files_absent(config_path)


def test_legacy_values_move_to_daily_tasks_with_task_precedence(
    config_path: Path,
) -> None:
    document = {
        "schema_version": 1,
        "revision": 7,
        "timezone": "UTC",
        "indicators": {"max_active_indicators": 20},
        "markets": {
            market: {
                "provider": provider,
                "history_years": 4,
                "symbols": [],
                "request_timeout_seconds": 30,
                "max_retries": 3,
                "concurrency": 2,
                "overlap_days": 90,
            }
            for market, provider in (
                ("a_share", "akshare"),
                ("hk_stock", "akshare"),
                ("us_stock", "yfinance"),
            )
        }
        | {
            "crypto": {
                "provider": "binance",
                "history_years": None,
                "symbols": DEFAULT_SPOT_PAIRS,
                "request_timeout_seconds": 30,
                "max_retries": 3,
                "concurrency": 2,
                "overlap_days": 90,
            }
        },
        "tasks": {
            "market.sync_a_daily": {
                "enabled": False,
                "cron": "0 0 * * *",
                "params": {"history_years": 8, "overlap_days": 15},
            }
        },
    }
    original = deepcopy(document)
    config_path.write_text(json.dumps(document), encoding="utf-8")

    settings = ConfigService(config_path).get()

    assert settings.revision == 7
    assert settings.schema_version == 1
    a_params = settings.tasks["market.sync_a_daily"].params
    assert a_params == {"history_years": 8, "overlap_days": 15, "concurrency": 2}
    for task_name in ("market.sync_hk_daily", "market.sync_us_daily"):
        params = settings.tasks[task_name].params
        assert params == {
            "history_years": 4,
            "overlap_days": 90,
            "concurrency": 2,
        }
        assert "max_retries" not in params
    assert settings.tasks["market.sync_crypto_daily"].params == {
        "history_years": None,
        "overlap_days": 90,
        "concurrency": 2,
        "spot_pairs": DEFAULT_SPOT_PAIRS,
    }
    for market in settings.markets.values():
        assert "history_years" not in market.model_fields_set
        assert "overlap_days" not in market.model_fields_set
        assert "concurrency" not in market.model_fields_set
        assert "max_retries" not in market.model_fields_set
        assert "symbols" not in market.model_fields_set
    assert document == original


def test_legacy_values_create_daily_tasks_when_tasks_section_is_missing(
    config_path: Path,
) -> None:
    base = ConfigService(config_path).get().model_dump(mode="python")
    markets = {
        name: {
            **market,
            "history_years": 4,
            "overlap_days": 90,
            "concurrency": 2,
            "max_retries": 3,
        }
        for name, market in base["markets"].items()
    }
    markets = {
        **markets,
        "crypto": {**markets["crypto"], "symbols": DEFAULT_SPOT_PAIRS},
    }
    document = {
        key: value for key, value in base.items() if key not in {"markets", "tasks"}
    } | {"revision": 7, "markets": markets}
    original = deepcopy(document)
    config_path.write_text(json.dumps(document), encoding="utf-8")

    settings = ConfigService(config_path).get()

    assert settings.revision == 7
    assert settings.schema_version == 1
    for task_name in (
        "market.sync_a_daily",
        "market.sync_hk_daily",
        "market.sync_us_daily",
    ):
        assert settings.tasks[task_name].params == {
            "history_years": 4,
            "overlap_days": 90,
            "concurrency": 2,
        }
    assert settings.tasks["market.sync_crypto_daily"].params == {
        "history_years": 4,
        "overlap_days": 90,
        "concurrency": 2,
        "spot_pairs": DEFAULT_SPOT_PAIRS,
    }
    for market in settings.markets.values():
        assert "history_years" not in market.model_fields_set
        assert "overlap_days" not in market.model_fields_set
        assert "concurrency" not in market.model_fields_set
        assert "max_retries" not in market.model_fields_set
        assert "symbols" not in market.model_fields_set
    assert document == original


def test_legacy_crypto_pairs_do_not_override_explicit_empty_task_directory(
    config_path: Path,
) -> None:
    base = ConfigService(config_path).get().model_dump(mode="python")
    document = {
        key: value for key, value in base.items() if key not in {"markets", "tasks"}
    } | {
        "revision": 7,
        "markets": {
            **base["markets"],
            "crypto": {
                **base["markets"]["crypto"],
                "symbols": DEFAULT_SPOT_PAIRS,
            },
        },
        "tasks": {
            "market.sync_crypto_daily": {
                "enabled": False,
                "cron": "0 0 * * *",
                "params": {"spot_pairs": []},
            }
        },
    }
    original = deepcopy(document)
    config_path.write_text(json.dumps(document), encoding="utf-8")

    settings = ConfigService(config_path).get()

    assert settings.revision == 7
    assert settings.schema_version == 1
    assert settings.tasks["market.sync_crypto_daily"].params["spot_pairs"] == []
    assert all(
        "symbols" not in market.model_fields_set
        for market in settings.markets.values()
    )
    assert document == original
