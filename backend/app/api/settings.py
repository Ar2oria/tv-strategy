"""Revision-checked full-document settings read and hot-update routes."""

from copy import deepcopy
from typing import Literal

from app.api.responses import success_response
from app.api.schemas import FrozenAPIInput
from app.config.models import (
    IndicatorSettings,
    MarketSettings,
    Settings,
    TaskSettings,
)
from app.config.store import ConfigService
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field

router = APIRouter(prefix="/api/v1", tags=["settings"])


class SettingsUpdate(FrozenAPIInput):
    """A complete candidate document plus its optimistic-concurrency token."""

    schema_version: Literal[1] = 1
    expected_revision: int = Field(ge=0)
    markets: dict[str, MarketSettings]
    timezone: str
    indicators: IndicatorSettings
    tasks: dict[str, TaskSettings]

    def to_settings(self) -> Settings:
        """Build a new immutable document; ConfigService assigns the revision."""
        return Settings(
            schema_version=self.schema_version,
            revision=0,
            markets=deepcopy(self.markets),
            timezone=self.timezone,
            indicators=self.indicators.model_copy(deep=True),
            tasks=deepcopy(self.tasks),
        )


def _config(request: Request) -> ConfigService:
    service = getattr(request.app.state, "config_service", None)
    if not isinstance(service, ConfigService):
        raise RuntimeError("Configuration service is not configured")
    return service


@router.get("/settings")
def get_settings(request: Request) -> JSONResponse:
    return success_response(_config(request).get())


@router.put("/settings")
def put_settings(request: Request, payload: SettingsUpdate) -> JSONResponse:
    updated = _config(request).update(
        payload.expected_revision,
        lambda old: payload.to_settings(),
    )
    return success_response(updated)
