"""Built-in Task for independent, atomic current-universe refreshes."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.errors import ProviderConfigurationError, ProviderError
from app.providers.hstech_api import ItigerUniverseProvider
from app.services.universe_sync_service import UniverseSyncService
from app.tasks.base import (
    Task,
    TaskContext,
    TaskParams,
    TaskResult,
    require_task_params,
)
from app.tasks.registry import register_task

ALL_UNIVERSES = (
    "csi300",
    "star_market",
    "chinext",
    "hstech",
    "nasdaq100",
    "soxx",
)
UNIVERSE_MARKETS = {
    "csi300": "a_share",
    "star_market": "a_share",
    "chinext": "a_share",
    "hstech": "hk_stock",
    "nasdaq100": "us_stock",
    "soxx": "us_stock",
}
UNIVERSE_FAILURE_MESSAGE = "Universe synchronization failed"
UNIVERSE_SUCCESS_MESSAGE = "Universe synchronization succeeded"


class UniverseSyncParams(TaskParams):
    """Refresh all known universes by default or an explicit subset."""

    universe_codes: tuple[str, ...] = ()
    itiger_token: str = Field(
        default="",
        max_length=4_096,
        title="iTiger Token",
        description="留空则使用默认 Token；保存到配置文件，不会写入运行历史或日志。",
    )

    @field_validator("universe_codes")
    @classmethod
    def codes_must_not_be_blank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("Universe codes must not be blank")
        return normalized


@register_task
class SyncUniversesTask(Task):
    name: ClassVar[str] = "market.sync_universes"
    display_name: ClassVar[str] = "Synchronize market universes"
    description: ClassVar[str] = "Atomically refresh current universe memberships"
    params_model: ClassVar[type[BaseModel]] = UniverseSyncParams

    async def run(self, context: TaskContext, params: BaseModel) -> TaskResult:
        validated = require_task_params(params, UniverseSyncParams)
        registry = context.resources.provider_registry
        if registry is None:
            raise RuntimeError("Market provider registry is not configured")
        codes = tuple(dict.fromkeys(validated.universe_codes or ALL_UNIVERSES))
        service = UniverseSyncService(context.resources.instrument_repository)
        succeeded = 0
        failures: list[dict[str, str]] = []
        member_count = 0
        for current, code in enumerate(codes, start=1):
            try:
                provider = registry.get_universe(code)
                if code == "hstech" and validated.itiger_token.strip():
                    if not isinstance(provider, ItigerUniverseProvider):
                        raise ProviderConfigurationError(
                            "iTiger provider is not configured for token override"
                        )
                    provider = ItigerUniverseProvider(
                        request_timeout_seconds=provider.request_timeout_seconds,
                        proxy_url=provider.proxy_url,
                        bearer_token=validated.itiger_token.strip(),
                    )
                market = UNIVERSE_MARKETS.get(code)
                timeout = (
                    context.settings.markets[market].request_timeout_seconds
                    if market is not None
                    else None
                )
                outcome = await service.sync_universe(
                    code,
                    provider,
                    timeout=timeout,
                )
            except Exception as error:
                failures = [
                    *failures,
                    {
                        "universe_code": code,
                        "detail": _safe_detail(error),
                    },
                ]
                context.log(
                    "ERROR",
                    UNIVERSE_FAILURE_MESSAGE,
                    run_id=context.run_id,
                    universe_code=code,
                    error_type=type(error).__name__,
                    detail=_safe_detail(error),
                )
            else:
                succeeded += 1
                member_count += outcome.member_count
                context.log(
                    "INFO",
                    UNIVERSE_SUCCESS_MESSAGE,
                    run_id=context.run_id,
                    universe_code=code,
                    instrument_count=outcome.instrument_count,
                    member_count=outcome.member_count,
                )
            context.report_progress(current * 100 / len(codes))

        failed = len(failures)
        status = _status(succeeded, failed)
        return TaskResult(
            status=status,
            error=_error(status, failed, len(codes)),
            details={
                "total": len(codes),
                "succeeded": succeeded,
                "failed": failed,
                "current": len(codes),
                "current_universe": codes[-1],
                "member_count": member_count,
                "failures": failures,
            },
        )


def _safe_detail(error: Exception) -> str:
    if isinstance(error, ProviderError):
        return error.public_detail
    return UNIVERSE_FAILURE_MESSAGE


def _status(succeeded: int, failed: int) -> Literal["success", "partial", "failed"]:
    if failed == 0:
        return "success"
    if succeeded == 0:
        return "failed"
    return "partial"


def _error(status: str, failed: int, total: int) -> str | None:
    if status == "success":
        return None
    if status == "failed":
        return "All universe synchronizations failed"
    return f"{failed} of {total} universe synchronizations failed"


MarketSyncUniversesTask = SyncUniversesTask

__all__ = [
    "ALL_UNIVERSES",
    "MarketSyncUniversesTask",
    "SyncUniversesTask",
    "UniverseSyncParams",
]
