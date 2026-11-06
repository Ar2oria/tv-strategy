"""Active instrument search and universe read endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.responses import success_response
from app.api.schemas import InstrumentsQuery
from app.repositories.instruments import InstrumentRepository

router = APIRouter(prefix="/api/v1", tags=["instruments"])


def _repository(request: Request) -> InstrumentRepository:
    repository = getattr(request.app.state, "instrument_repository", None)
    if not isinstance(repository, InstrumentRepository):
        raise RuntimeError("Instrument repository is not configured")
    return repository


@router.get("/instruments")
def list_instruments(
    request: Request,
    filters: Annotated[InstrumentsQuery, Query()],
) -> JSONResponse:
    """Search active instruments with bounded, parameterized filters."""
    records = _repository(request).list_instruments(
        market=filters.market,
        universe_code=filters.universe_code,
        query=filters.query,
        active=True,
        limit=filters.limit,
        offset=filters.offset,
    )
    return success_response(
        records,
        meta={
            "count": len(records),
            "limit": filters.limit,
            "offset": filters.offset,
        },
    )


@router.get("/universes")
def list_universes(request: Request) -> JSONResponse:
    """Return stable universe codes in lexical order."""
    universes = _repository(request).list_universes()
    return success_response(universes, meta={"count": len(universes)})
