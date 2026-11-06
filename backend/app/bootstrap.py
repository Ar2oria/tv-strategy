"""Startup migrations, discovery, configuration reconciliation, and shutdown."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.config.application import AppSettings
from app.config.models import Settings, TaskSettings
from app.config.store import ConfigService
from app.container import ApplicationContainer
from app.db.database import SessionFactory, database_url
from app.indicators.discovery import discover_indicators
from app.indicators.registry import IndicatorRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.repositories.task_runs import TaskRunRepository
from app.services.bar_service import BarService
from app.services.cron_scheduler import CronScheduler
from app.services.indicator_cache import IndicatorCache
from app.services.indicator_service import IndicatorService
from app.services.resources import RuntimeResources
from app.services.task_runner import TaskRunner
from app.services.task_service import TaskService
from app.tasks.discovery import discover_tasks
from app.tasks.registry import TaskRegistry

logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SettingsListener = Callable[[Settings], None]


def migrate_database(database_path: Path) -> None:
    """Upgrade only the configured temporary/local SQLite database."""
    resolved = database_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url(resolved))
    command.upgrade(config, "head")


def build_container(settings: AppSettings) -> ApplicationContainer:
    """Construct dependencies without scheduling work or downloading markets."""
    config = ConfigService(settings.config_path)
    migrate_database(settings.database_path)
    indicator_registry = discover_indicators()
    task_registry = discover_tasks()
    sessions = SessionFactory(settings.database_path)
    try:
        instruments = InstrumentRepository(sessions)
        bars = BarRepository(sessions)
        task_runs = TaskRunRepository(sessions)
        bar_service = BarService(bars, instruments)
        indicator_cache = IndicatorCache()
        current = config.get()
        indicator_service = _indicator_service(
            current,
            bar_service,
            instruments,
            indicator_registry,
            indicator_cache,
        )
        resources = RuntimeResources(
            instrument_repository=instruments,
            bar_repository=bars,
        )
        runner = TaskRunner(task_registry, task_runs, config, resources)
        scheduler = CronScheduler(runner, task_registry)
        task_service = TaskService(config, task_registry, task_runs, runner)
        return ApplicationContainer(
            app_settings=settings,
            sessions=sessions,
            config_service=config,
            indicator_registry=indicator_registry,
            task_registry=task_registry,
            instrument_repository=instruments,
            bar_repository=bars,
            task_run_repository=task_runs,
            bar_service=bar_service,
            indicator_service=indicator_service,
            task_service=task_service,
            task_runner=runner,
            cron_scheduler=scheduler,
            resources=resources,
        )
    except Exception:
        sessions.dispose()
        raise


def configure_container(
    container: ApplicationContainer,
    *,
    provider_listener: SettingsListener,
    indicator_listener: SettingsListener,
) -> None:
    """Register validation before writes and hot listeners after persistence."""
    config = container.config_service
    config.add_validator(container.task_service.validate_settings)
    config.subscribe(provider_listener)
    config.subscribe(indicator_listener)
    config.subscribe(container.cron_scheduler.apply_settings)


def start_container(container: ApplicationContainer) -> None:
    """Reconcile Task defaults, recreate future jobs, then start scheduling."""
    ensure_task_configs(container.config_service, container.task_registry)
    container.cron_scheduler.apply_settings(container.config_service.get())
    container.cron_scheduler.start()


def ensure_task_configs(config: ConfigService, registry: TaskRegistry) -> bool:
    """Add missing disabled configs for registered Tasks, preserving all others."""
    registered = {descriptor.name for descriptor in registry.descriptors}
    if registered <= set(config.get().tasks):
        return False

    def add_missing(old: Settings) -> Settings:
        missing = {
            name: TaskSettings(enabled=False)
            for name in sorted(registered - set(old.tasks))
        }
        return old.model_copy(update={"tasks": {**old.tasks, **missing}})

    config.update(config.get().revision, add_missing)
    return True


async def shutdown_container(container: ApplicationContainer, timeout: float) -> None:
    """Stop scheduling, wait for Tasks within a deadline, then release SQLite."""
    try:
        container.cron_scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("CronScheduler shutdown failed")
    try:
        try:
            await asyncio.wait_for(container.task_runner.aclose(), timeout)
        except TimeoutError:
            logger.error(
                "Timed out waiting for TaskRunner shutdown after %s seconds", timeout
            )
        except Exception:
            logger.exception("TaskRunner shutdown failed")
    finally:
        try:
            container.session_factory.dispose()
        except Exception:
            logger.exception("SQLite engine disposal failed")


def _indicator_service(
    settings: Settings,
    bars: BarService,
    instruments: InstrumentRepository,
    registry: IndicatorRegistry,
    cache: IndicatorCache,
) -> IndicatorService:
    return IndicatorService(
        bar_service=bars,
        instruments=instruments,
        registry=registry,
        settings=settings.model_copy(deep=True),
        cache=cache,
    )
