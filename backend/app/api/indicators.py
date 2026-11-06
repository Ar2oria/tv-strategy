"""Indicator descriptor and asynchronous batch-compute endpoints."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.responses import success_response
from app.api.schemas import IndicatorComputeRequest
from app.indicators.registry import IndicatorRegistry
from app.services.indicator_service import IndicatorService

router = APIRouter(prefix="/api/v1", tags=["indicators"])


def _registry(request: Request) -> IndicatorRegistry:
    registry = getattr(request.app.state, "indicator_registry", None)
    if not isinstance(registry, IndicatorRegistry):
        raise RuntimeError("Indicator registry is not configured")
    return registry


def _service(request: Request) -> IndicatorService:
    service = getattr(request.app.state, "indicator_service", None)
    if not isinstance(service, IndicatorService):
        raise RuntimeError("Indicator service is not configured")
    return service


@router.get("/indicators")
def list_indicators(request: Request) -> JSONResponse:
    """Expose immutable descriptors and their parameter JSON Schemas."""
    descriptors = [
        descriptor.model_dump(mode="json")
        for descriptor in _registry(request).descriptors
    ]
    return success_response(descriptors, meta={"count": len(descriptors)})


@router.post("/indicators/compute")
async def compute_indicators(
    request: Request, payload: IndicatorComputeRequest
) -> JSONResponse:
    """Run synchronous SQL and calculations outside the async event loop."""
    computations = await asyncio.to_thread(_service(request).compute, payload)
    return success_response(computations, meta={"count": len(computations)})
