"""Application-owned dependencies and atomic hot-runtime replacements."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

from app.config.application import AppSettings
from app.config.models import IndicatorSettings, MarketSettings, Settings
from app.config.store import ConfigService
from app.db.database import SessionFactory
from app.indicators.registry import IndicatorRegistry
from app.providers.factory import build_provider_registry
from app.providers.registry import ProviderRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.repositories.task_runs import TaskRunRepository
from app.services.bar_service import BarService
from app.services.indicator_cache import IndicatorCache
from app.services.bar_sync_service import BarSyncService
from app.services.cron_scheduler import CronScheduler
from app.services.indicator_service import IndicatorService
from app.services.resources import RuntimeResources
from app.services.task_runner import TaskRunner
from app.services.task_service import TaskService
from app.tasks.registry import TaskRegistry


@dataclass(frozen=True, slots=True)
class _IndicatorRuntime:
    service: IndicatorService
    settings: IndicatorSettings


class ApplicationContainer:
    """Expose core services while replacing hot state as immutable snapshots."""

    def __init__(
        self,
        *,
        app_settings: AppSettings,
        sessions: SessionFactory,
        config_service: ConfigService,
        indicator_registry: IndicatorRegistry,
        task_registry: TaskRegistry,
        instrument_repository: InstrumentRepository,
        bar_repository: BarRepository,
        task_run_repository: TaskRunRepository,
        bar_service: BarService,
        indicator_service: IndicatorService,
        task_service: TaskService,
        task_runner: TaskRunner,
        cron_scheduler: CronScheduler,
        resources: RuntimeResources,
        provider_registry_factory: Callable[[Settings], ProviderRegistry] | None = None,
        indicator_cache: IndicatorCache | None = None,
    ) -> None:
        current = config_service.get()
        self.app_settings = app_settings
        self.session_factory = sessions
        self.config_service = config_service
        self.indicator_registry = indicator_registry
        self.task_registry = task_registry
        self.instrument_repository = instrument_repository
        self.bar_repository = bar_repository
        self.task_run_repository = task_run_repository
        self.bar_service = bar_service
        self.task_service = task_service
        self.task_runner = task_runner
        self.cron_scheduler = cron_scheduler
        self.resources = resources
        self._indicator_runtime = _IndicatorRuntime(
            service=indicator_service,
            settings=current.indicators.model_copy(deep=True),
        )
        self._indicator_cache = indicator_cache or IndicatorCache()
        self._provider_settings = deepcopy(current.markets)
        self._provider_registry_factory = (
            provider_registry_factory or build_provider_registry
        )
        self.apply_provider_settings(current)

    @property
    def config(self) -> ConfigService:
        return self.config_service

    @property
    def runner(self) -> TaskRunner:
        return self.task_runner

    @property
    def scheduler(self) -> CronScheduler:
        return self.cron_scheduler

    @property
    def indicator_service(self) -> IndicatorService:
        return self._indicator_runtime.service

    @property
    def indicator_cache(self) -> IndicatorCache:
        return self._indicator_cache

    @property
    def indicator_settings(self) -> IndicatorSettings:
        return self._indicator_runtime.settings.model_copy(deep=True)

    @property
    def provider_settings(self) -> dict[str, MarketSettings]:
        return deepcopy(self._provider_settings)

    @property
    def provider_registry(self) -> ProviderRegistry:
        registry = self.resources.provider_registry
        if registry is None:
            raise RuntimeError("Market provider registry is not configured")
        return registry

    def apply_provider_settings(self, settings: Settings) -> None:
        """Build and publish fresh providers/resources without provider I/O."""
        validated = Settings.model_validate(settings.model_dump(mode="python"))
        registry = self._provider_registry_factory(validated.model_copy(deep=True))
        if not isinstance(registry, ProviderRegistry):
            raise TypeError("provider_registry_factory must return ProviderRegistry")
        resources = RuntimeResources(
            instrument_repository=self.instrument_repository,
            bar_repository=self.bar_repository,
            provider_registry=registry,
            bar_sync_service=BarSyncService(
                self.bar_repository, cache=self._indicator_cache
            ),
        )
        provider_settings = deepcopy(validated.markets)
        self.task_runner.replace_resources(resources)
        self.resources = resources
        self._provider_settings = provider_settings

    def apply_indicator_settings(self, settings: Settings) -> None:
        """Replace the service only when indicator limits actually change."""
        validated = Settings.model_validate(settings.model_dump(mode="python"))
        if validated.indicators == self._indicator_runtime.settings:
            return
        replacement = IndicatorService(
            bar_service=self.bar_service,
            instruments=self.instrument_repository,
            registry=self.indicator_registry,
            settings=validated.model_copy(deep=True),
            cache=self._indicator_cache,
        )
        self._indicator_runtime = _IndicatorRuntime(
            service=replacement,
            settings=validated.indicators.model_copy(deep=True),
        )
