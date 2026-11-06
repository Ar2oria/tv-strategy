"""Read-only daily, ISO-weekly, and calendar-monthly bar endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.responses import success_response
from app.api.schemas import BarsQuery
from app.services.bar_service import BarService

router = APIRouter(prefix="/api/v1", tags=["bars"])


def _service(request: Request) -> BarService:
    service = getattr(request.app.state, "bar_service", None)
    if not isinstance(service, BarService):
        raise RuntimeError("Bar service is not configured")
    return service


@router.get("/bars")
def read_bars(
    request: Request,
    filters: Annotated[BarsQuery, Query()],
) -> JSONResponse:
    """Return actual trading dates after aggregation and visible-range trimming."""
    bars = _service(request).get_visible(
        filters.instrument_id,
        filters.timeframe,
        filters.start,
        filters.end,
        filters.limit,
    )
    return success_response(
        bars,
        meta={"count": len(bars), "timeframe": filters.timeframe},
    )
