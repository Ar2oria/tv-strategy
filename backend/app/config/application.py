"""Process-local application settings, separate from hot JSON Settings."""

import os
from pathlib import Path
from typing import Literal

from app.config.models import FrozenSettingsModel
from app.middleware.targets import normalize_host, normalize_origin
from pydantic import Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "backend.sqlite3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")
DEFAULT_PORT = 8000
UVICORN_WORKERS = 1
DEFAULT_MAX_REQUEST_BODY_BYTES = 1_048_576
DEFAULT_READ_RATE_LIMIT = 120
DEFAULT_WRITE_RATE_LIMIT = 30
DEFAULT_COMPUTE_RATE_LIMIT = 10
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0
DEFAULT_RATE_LIMIT_MAX_ENTRIES = 4_096
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 10.0
DEFAULT_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_DIST_ENV = "STOCK_LAB_FRONTEND_DIST"


class AppSettings(FrozenSettingsModel):
    """Own filesystem/server options and deterministic test limit overrides."""

    config_path: Path = DEFAULT_CONFIG_PATH
    database_path: Path = DEFAULT_DATABASE_PATH
    host: str = DEFAULT_HOST
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65_535)
    workers: Literal[1] = UVICORN_WORKERS
    max_request_body_bytes: int = Field(
        default=DEFAULT_MAX_REQUEST_BODY_BYTES,
        ge=1,
        le=16_777_216,
    )
    read_rate_limit: int = Field(default=DEFAULT_READ_RATE_LIMIT, ge=1)
    write_rate_limit: int = Field(default=DEFAULT_WRITE_RATE_LIMIT, ge=1)
    compute_rate_limit: int = Field(default=DEFAULT_COMPUTE_RATE_LIMIT, ge=1)
    rate_limit_window_seconds: float = Field(
        default=DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        gt=0,
        le=3_600,
    )
    rate_limit_max_entries: int = Field(
        default=DEFAULT_RATE_LIMIT_MAX_ENTRIES,
        ge=1,
    )
    shutdown_timeout_seconds: float = Field(
        default=DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
        gt=0,
        le=60,
    )
    frontend_dist: Path | None = None
    serve_frontend: bool = True

    def default_frontend_dist(self) -> Path | None:
        """Return the built bundle beside the repository, never the CWD."""
        return DEFAULT_FRONTEND_DIST if DEFAULT_FRONTEND_DIST.is_dir() else None

    def resolved_frontend_dist(self, candidate: Path | None = None) -> Path | None:
        """Prefer an explicit path, then the env override, then the default."""
        if not self.serve_frontend:
            return None
        explicit = candidate if candidate is not None else self.frontend_dist
        if explicit is not None:
            return explicit if explicit.is_dir() else None
        override = os.environ.get(FRONTEND_DIST_ENV)
        if override is not None and override.strip():
            path = Path(override).expanduser()
            return path if path.is_dir() else None
        return self.default_frontend_dist()

    @field_validator("host")
    @classmethod
    def host_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Application host must not be blank")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def allowed_hosts_must_be_exact(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("At least one allowed Host is required")
        return tuple(normalize_host(value) for value in values)

    @field_validator("allowed_origins")
    @classmethod
    def allowed_origins_must_be_exact(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        return tuple(normalize_origin(value) for value in values)
