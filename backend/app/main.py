"""FastAPI composition root for one local Uvicorn worker."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.api.bars import router as bars_router
from app.api.errors import register_application_error_handlers
from app.api.indicators import router as indicators_router
from app.api.instruments import router as instruments_router
from app.api.market_network_test import router as market_network_test_router
from app.api.responses import register_response_handlers
from app.api.settings import router as settings_router
from app.api.tasks import router as tasks_router
from app.bootstrap import (
    build_container,
    configure_container,
    shutdown_container,
    start_container,
)
from app.config.application import UVICORN_WORKERS, AppSettings
from app.config.models import Settings
from app.container import ApplicationContainer
from app.middleware.rate_limit import RateLimitMiddleware, RateLimitPolicy
from app.middleware.request_limits import RequestBodyLimitMiddleware
from app.middleware.request_trust import (
    BrowserRequestTrustMiddleware,
    SanitizedTrustedHostMiddleware,
)
from app.static_frontend import configure_frontend
from fastapi import FastAPI

__all__ = ["AppSettings", "UVICORN_WORKERS", "app", "create_app"]


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create an isolated app; filesystem/startup work begins inside lifespan."""
    app_settings = settings if settings is not None else AppSettings()
    if not isinstance(app_settings, AppSettings):
        raise TypeError("create_app settings must be an AppSettings instance")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        container: ApplicationContainer | None = None
        try:
            container = build_container(app_settings)
            active_container = container
            _publish_container(application, active_container)

            def apply_provider(candidate: Settings) -> None:
                active_container.apply_provider_settings(candidate)
                application.state.provider_registry = active_container.provider_registry
                application.state.resources = active_container.resources

            def apply_indicator(candidate: Settings) -> None:
                active_container.apply_indicator_settings(candidate)
                application.state.indicator_service = active_container.indicator_service
                application.state.indicator_settings = (
                    active_container.indicator_settings
                )

            configure_container(
                container,
                provider_listener=apply_provider,
                indicator_listener=apply_indicator,
            )
            start_container(container)
            yield
        finally:
            if container is not None:
                await shutdown_container(
                    container,
                    app_settings.shutdown_timeout_seconds,
                )

    application = FastAPI(title="TV Strategy Local Backend", lifespan=lifespan)
    application.state.app_settings = app_settings
    _register_routes(application)
    configure_frontend(application, app_settings.resolved_frontend_dist())
    register_response_handlers(application)
    register_application_error_handlers(application)
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=app_settings.max_request_body_bytes,
    )
    application.add_middleware(
        RateLimitMiddleware,
        policy=RateLimitPolicy(
            read=app_settings.read_rate_limit,
            write=app_settings.write_rate_limit,
            compute=app_settings.compute_rate_limit,
            window_seconds=app_settings.rate_limit_window_seconds,
            max_entries=app_settings.rate_limit_max_entries,
        ),
    )
    application.add_middleware(
        BrowserRequestTrustMiddleware,
        allowed_origins=app_settings.allowed_origins,
    )
    application.add_middleware(
        SanitizedTrustedHostMiddleware,
        allowed_hosts=app_settings.allowed_hosts,
    )
    return application


def _register_routes(application: FastAPI) -> None:
    application.include_router(instruments_router)
    application.include_router(market_network_test_router)
    application.include_router(bars_router)
    application.include_router(indicators_router)
    application.include_router(tasks_router)
    application.include_router(settings_router)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}


def _publish_container(
    application: FastAPI,
    container: ApplicationContainer,
) -> None:
    application.state.container = container
    application.state.config_service = container.config_service
    application.state.instrument_repository = container.instrument_repository
    application.state.bar_repository = container.bar_repository
    application.state.task_run_repository = container.task_run_repository
    application.state.bar_service = container.bar_service
    application.state.indicator_registry = container.indicator_registry
    application.state.indicator_service = container.indicator_service
    application.state.indicator_settings = container.indicator_settings
    application.state.task_registry = container.task_registry
    application.state.task_service = container.task_service
    application.state.task_runner = container.task_runner
    application.state.cron_scheduler = container.cron_scheduler
    application.state.resources = container.resources
    application.state.provider_registry = container.provider_registry


app = create_app()
