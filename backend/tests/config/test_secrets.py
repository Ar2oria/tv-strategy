"""Sensitive configuration snapshots must not share mutable nested values."""

from app.config.defaults import default_settings
from app.config.models import Settings
from app.config.secrets import mask_sensitive_settings, restore_sensitive_settings

TASK_NAME = "market.sync_universes"


def settings_with_nested_params() -> Settings:
    settings = default_settings()
    task = settings.tasks[TASK_NAME]
    configured = task.model_copy(
        update={
            "params": {
                "universe_codes": ["hstech"],
                "itiger_token": "configured-token",
            }
        }
    )
    return settings.model_copy(
        update={"tasks": {**settings.tasks, TASK_NAME: configured}}
    )


def test_masked_settings_deep_copy_nested_task_params() -> None:
    original = settings_with_nested_params()

    masked = mask_sensitive_settings(original)

    universes = masked.tasks[TASK_NAME].params["universe_codes"]
    assert isinstance(universes, list)
    universes.append("soxx")
    assert original.tasks[TASK_NAME].params["universe_codes"] == ["hstech"]


def test_restored_settings_deep_copy_nested_task_params() -> None:
    current = settings_with_nested_params()
    candidate = mask_sensitive_settings(current)

    restored = restore_sensitive_settings(candidate, current)

    assert restored.tasks[TASK_NAME].params["itiger_token"] == "configured-token"
    universes = restored.tasks[TASK_NAME].params["universe_codes"]
    assert isinstance(universes, list)
    universes.append("soxx")
    assert candidate.tasks[TASK_NAME].params["universe_codes"] == ["hstech"]
