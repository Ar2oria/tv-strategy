"""Task catalog, configuration, immediate execution, history, and log routes."""

from typing import Annotated, Self

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, JsonValue, model_validator

from app.api.responses import success_response
from app.api.schemas import FrozenAPIInput
from app.repositories.task_runs import MAX_PAGE_SIZE
from app.services.task_service import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_LOG_LIMIT,
    TaskService,
)

router = APIRouter(prefix="/api/v1", tags=["tasks"])
MAX_PAGE_OFFSET = 100_000
PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
PageOffset = Annotated[int, Query(ge=0, le=MAX_PAGE_OFFSET)]


class TaskConfigUpdate(FrozenAPIInput):
    expected_revision: int = Field(ge=0)
    enabled: bool | None = None
    cron: str | None = None
    params: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def contains_change(self) -> Self:
        if self.enabled is None and self.cron is None and self.params is None:
            raise ValueError("At least one Task configuration field is required")
        return self


class TaskRunRequest(FrozenAPIInput):
    params: dict[str, JsonValue] | None = None
    params_override: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def one_params_field(self) -> Self:
        if self.params is not None and self.params_override is not None:
            raise ValueError("Use only one of params and params_override")
        return self

    @property
    def override(self) -> dict[str, JsonValue] | None:
        return self.params if self.params is not None else self.params_override


def _service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if not isinstance(service, TaskService):
        raise RuntimeError("Task service is not configured")
    return service


@router.get("/tasks")
def list_tasks(request: Request) -> JSONResponse:
    tasks = _service(request).list_tasks()
    return success_response(tasks, meta={"count": len(tasks)})


@router.get("/tasks/{task_name}/config")
def get_task_config(task_name: str, request: Request) -> JSONResponse:
    return success_response(_service(request).get_config(task_name))


@router.put("/tasks/{task_name}/config")
def update_task_config(
    task_name: str, request: Request, payload: TaskConfigUpdate
) -> JSONResponse:
    updated = _service(request).update_config(
        task_name,
        payload.expected_revision,
        enabled=payload.enabled,
        cron=payload.cron,
        params=payload.params,
    )
    return success_response(updated)


@router.post("/tasks/{task_name}/runs", status_code=202)
async def start_task_run(
    task_name: str, request: Request, payload: TaskRunRequest | None = None
) -> JSONResponse:
    override = payload.override if payload is not None else None
    run = await _service(request).run_now(task_name, override)
    return success_response(run, status_code=202)


@router.get("/tasks/{task_name}/runs")
def get_task_runs(
    task_name: str,
    request: Request,
    limit: PageLimit = DEFAULT_HISTORY_LIMIT,
    offset: PageOffset = 0,
) -> JSONResponse:
    runs = _service(request).history(task_name, limit=limit, offset=offset)
    return success_response(
        runs,
        meta={
            "count": len(runs),
            "task_name": task_name,
            "limit": limit,
            "offset": offset,
        },
    )


@router.get("/task-runs/{run_id}/logs")
def get_task_logs(
    run_id: Annotated[int, Path(gt=0)],
    request: Request,
    limit: PageLimit = DEFAULT_LOG_LIMIT,
    offset: PageOffset = 0,
) -> JSONResponse:
    logs = _service(request).logs(run_id, limit=limit, offset=offset)
    return success_response(
        logs,
        meta={"count": len(logs), "run_id": run_id, "limit": limit, "offset": offset},
    )
