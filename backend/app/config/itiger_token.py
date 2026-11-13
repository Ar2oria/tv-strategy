"""Resolve the iTiger bearer token from config, environment, or local file."""

import os
from pathlib import Path

from app.config.models import Settings

ITIGER_TOKEN_ENV = "ITIGER_BEARER_TOKEN"
ITIGER_TOKEN_TASK = "market.sync_universes"
ITIGER_TOKEN_PARAM = "itiger_token"
ITIGER_TOKEN_FILE = Path(__file__).resolve().parents[3] / "config" / "itiger_token.txt"


def configured_itiger_token(settings: Settings | None) -> str | None:
    """Return the token persisted in the Task configuration, if any."""
    if settings is None:
        return None
    task = settings.tasks.get(ITIGER_TOKEN_TASK)
    if task is None:
        return None
    token = task.params.get(ITIGER_TOKEN_PARAM)
    if not isinstance(token, str):
        return None
    return token.strip() or None


def default_itiger_token(settings: Settings | None = None) -> str | None:
    """Prefer the persisted Task config, then the env, then the local file."""
    configured = configured_itiger_token(settings)
    if configured is not None:
        return configured
    from_env = os.environ.get(ITIGER_TOKEN_ENV)
    if from_env is not None and from_env.strip():
        return from_env.strip()
    try:
        from_file = ITIGER_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return from_file or None
