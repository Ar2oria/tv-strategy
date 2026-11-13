"""Saved-configuration, non-persisting market connectivity probes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from app.api.responses import error_response, success_response
from app.api.schemas import FrozenAPIInput
from app.domain.dto import Market
from app.providers.registry import ProviderRegistry
from app.services.market_network_test import (
    MarketNetworkTestService,
    NetworkTestInputError,
)

router = APIRouter(prefix="/api/v1/settings/markets", tags=["settings"])


class NetworkTestRequest(FrozenAPIInput):
    symbol: str = Field(min_length=1, max_length=64)

    @field_validator("symbol")
    @classmethod
    def symbol_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Symbol must not be blank")
        return normalized


def _registry(request: Request) -> ProviderRegistry:
    registry = getattr(request.app.state, "provider_registry", None)
    if not isinstance(registry, ProviderRegistry):
        raise RuntimeError("Market provider registry is not configured")
    return registry


@router.post("/{market}/network-test")
async def test_market_network(
    market: Market,
    request: Request,
    payload: NetworkTestRequest,
) -> JSONResponse:
    service = MarketNetworkTestService(_registry(request))
    try:
        result = await service.test(market, payload.symbol)
    except NetworkTestInputError:
        return error_response(
            "invalid_network_test_symbol",
            "Invalid symbol for this market",
            422,
        )
    return success_response(result)
