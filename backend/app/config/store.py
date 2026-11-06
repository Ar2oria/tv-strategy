"""Thread-safe hot JSON configuration with atomic rollback."""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, NoReturn, TypeAlias

from pydantic import ValidationError

from app.config.defaults import default_settings
from app.config.models import Settings

SettingsListener: TypeAlias = Callable[[Settings], None]
SettingsValidator: TypeAlias = Callable[[Settings], None]
SettingsBuilder: TypeAlias = Callable[[Settings], Settings]
TEMP_FILE_SUFFIX = ".tmp"


class ConfigError(Exception):
    """Base error for configuration operations."""


class ConfigConflictError(ConfigError):
    """Raised when an update uses a stale expected revision."""


class ConfigValidationError(ConfigError):
    """Raised when a candidate configuration is invalid."""


class ConfigApplyError(ConfigError):
    """Raised when persistence or post-persistence notification fails."""

    def __init__(
        self,
        message: str,
        *,
        original_error: Exception | None = None,
        rollback_errors: tuple[Exception, ...] = (),
    ) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.rollback_errors = rollback_errors


class ConfigService:
    """Own a settings document and serialize updates through an RLock."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._listeners: tuple[SettingsListener, ...] = ()
        self._validators: tuple[SettingsValidator, ...] = ()
        self._settings = self._load_or_create()

    def get(self) -> Settings:
        """Return a deep copy that cannot alter the stored state."""
        with self._lock:
            return self._settings.model_copy(deep=True)

    def subscribe(self, listener: SettingsListener) -> None:
        """Register a listener for persisted updates and rollback notices."""
        if not callable(listener):
            raise TypeError("Configuration listener must be callable")
        with self._lock:
            self._listeners = (*self._listeners, listener)

    def add_validator(self, validator: SettingsValidator) -> None:
        """Register a validator to run before any update is persisted."""
        if not callable(validator):
            raise TypeError("Configuration validator must be callable")
        with self._lock:
            self._validators = (*self._validators, validator)

    def update(
        self,
        expected_revision: int,
        build_next: SettingsBuilder,
    ) -> Settings:
        """Validate and atomically persist one revision, then notify listeners."""
        if not callable(build_next):
            raise TypeError("Configuration builder must be callable")

        with self._lock:
            previous = self._settings
            self._check_revision(expected_revision, previous.revision)
            candidate = self._build_candidate(previous, build_next)
            self._run_validators(candidate)
            previous_document = self._read_bytes()
            self._write_atomically(self._serialize(candidate))
            self._settings = candidate

            try:
                self._notify(candidate)
            except Exception as error:
                self._rollback(previous, previous_document, error)

            return candidate.model_copy(deep=True)

    def _load_or_create(self) -> Settings:
        if not self._path.exists():
            settings = default_settings()
            self._write_atomically(self._serialize(settings))
            return settings
        return self._read_settings()

    def _read_settings(self) -> Settings:
        document = self._read_bytes()
        try:
            decoded = json.loads(document)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ConfigValidationError(
                f"Configuration file {self._path} is not valid JSON: {error}"
            ) from error
        try:
            return Settings.model_validate(decoded)
        except ValidationError as error:
            raise ConfigValidationError(
                f"Configuration file {self._path} is invalid: {error}"
            ) from error

    def _read_bytes(self) -> bytes:
        try:
            return self._path.read_bytes()
        except OSError as error:
            raise ConfigApplyError(
                f"Unable to read configuration file {self._path}: {error}"
            ) from error

    @staticmethod
    def _serialize(settings: Settings) -> bytes:
        return (settings.model_dump_json(indent=2) + "\n").encode("utf-8")

    @staticmethod
    def _check_revision(expected: int, actual: int) -> None:
        if expected != actual:
            raise ConfigConflictError(
                f"Expected configuration revision {expected}, but current "
                f"revision is {actual}"
            )

    def _build_candidate(
        self,
        previous: Settings,
        build_next: SettingsBuilder,
    ) -> Settings:
        try:
            built = build_next(previous.model_copy(deep=True))
        except ConfigError:
            raise
        except Exception as error:
            raise ConfigValidationError(
                f"Configuration builder failed: {error}"
            ) from error

        if not isinstance(built, Settings):
            raise ConfigValidationError(
                "Configuration builder must return a Settings instance"
            )

        revised = built.model_copy(update={"revision": previous.revision + 1})
        try:
            document = revised.model_dump(mode="python")
            return Settings.model_validate(document)
        except (ValidationError, ValueError, TypeError) as error:
            raise ConfigValidationError(
                f"Candidate configuration is invalid: {error}"
            ) from error

    def _run_validators(self, candidate: Settings) -> None:
        for index, validator in enumerate(self._validators):
            try:
                validator(candidate.model_copy(deep=True))
            except ConfigValidationError:
                raise
            except Exception as error:
                raise ConfigValidationError(
                    f"Configuration validator {index} rejected the update: {error}"
                ) from error

    def _notify(self, settings: Settings) -> None:
        for listener in self._listeners:
            listener(settings.model_copy(deep=True))

    def _notify_best_effort(self, settings: Settings) -> tuple[Exception, ...]:
        errors: tuple[Exception, ...] = ()
        for listener in self._listeners:
            try:
                listener(settings.model_copy(deep=True))
            except Exception as error:
                errors = (*errors, error)
        return errors

    def _rollback(
        self,
        previous: Settings,
        previous_document: bytes,
        original_error: Exception,
    ) -> NoReturn:
        restore_error: Exception | None = None
        try:
            self._write_atomically(previous_document)
        except Exception as error:
            restore_error = error

        self._settings = previous
        notification_errors = self._notify_best_effort(previous)
        rollback_errors = (
            notification_errors
            if restore_error is None
            else (restore_error, *notification_errors)
        )
        restore_status = (
            "Previous document and runtime state were restored."
            if restore_error is None
            else f"Restoring the previous document failed: {restore_error}"
        )
        rollback_details = self._rollback_details(rollback_errors)
        raise ConfigApplyError(
            f"Configuration listener failed after persistence: {original_error}. "
            f"{restore_status}{rollback_details}",
            original_error=original_error,
            rollback_errors=rollback_errors,
        ) from original_error

    @staticmethod
    def _rollback_details(errors: tuple[Exception, ...]) -> str:
        if not errors:
            return " Rollback listeners were notified best-effort."
        details = "; ".join(str(error) for error in errors)
        return f" Rollback also encountered errors: {details}"

    def _write_atomically(self, document: bytes) -> None:
        temp_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=TEMP_FILE_SUFFIX,
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                stream.write(document)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self._path)
        except OSError as error:
            raise ConfigApplyError(
                f"Unable to atomically write configuration file "
                f"{self._path}: {error}"
            ) from error
        finally:
            self._remove_temp_file(temp_path)

    @staticmethod
    def _remove_temp_file(temp_path: Path | None) -> None:
        if temp_path is None:
            return
        try:
            temp_path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise ConfigApplyError(
                f"Unable to remove temporary configuration file "
                f"{temp_path}: {error}"
            ) from error
