"""Complete current-universe downloads with atomic membership replacement."""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.providers.base import UniverseProvider
from app.providers.errors import NoDataAvailable, ProviderDataInvalid
from app.repositories.instruments import InstrumentRepository
from app.services.provider_calls import call_provider_sync


@dataclass(frozen=True, slots=True)
class UniverseSyncOutcome:
    """One successfully replaced universe snapshot."""

    universe_code: str
    status: Literal["success"]
    instrument_count: int
    member_count: int


class UniverseSyncService:
    """Fetch and validate a complete snapshot before changing stored members."""

    def __init__(self, instrument_repository: InstrumentRepository) -> None:
        self._instruments = instrument_repository

    async def sync_universe(
        self,
        universe_code: str,
        provider: UniverseProvider,
        *,
        timeout: float | None = None,
    ) -> UniverseSyncOutcome:
        """Use a worker thread and an optional cooperative wait bound."""
        if not isinstance(universe_code, str) or not universe_code.strip():
            raise ValueError("universe_code must not be blank")
        snapshot = (
            await asyncio.to_thread(provider.fetch_universe, universe_code)
            if timeout is None
            else await call_provider_sync(
                provider.fetch_universe,
                universe_code,
                timeout=timeout,
            )
        )
        validated = _validate_snapshot(snapshot, universe_code)
        instrument_count, member_count = self._instruments.replace_universe(validated)
        return UniverseSyncOutcome(
            universe_code,
            "success",
            instrument_count,
            member_count,
        )


def _validate_snapshot(snapshot: object, requested_code: str) -> UniverseSnapshot:
    if not isinstance(snapshot, UniverseSnapshot):
        raise ProviderDataInvalid("Universe provider must return a UniverseSnapshot")
    if snapshot.universe_code != requested_code:
        raise ProviderDataInvalid("Universe snapshot code does not match the request")
    if not snapshot.members:
        raise NoDataAvailable(
            detail="Universe snapshot contains no members"
        )
    if not isinstance(snapshot.source, str) or not snapshot.source.strip():
        raise ProviderDataInvalid("Universe snapshot source must not be blank")
    if isinstance(snapshot.effective_date, datetime) or (
        snapshot.effective_date is not None
        and not isinstance(snapshot.effective_date, date)
    ):
        raise ProviderDataInvalid("Universe effective_date must be a date or None")
    instruments = (*snapshot.related_instruments, *snapshot.members)
    if any(not isinstance(item, InstrumentDTO) for item in instruments):
        raise ProviderDataInvalid("Universe snapshot contains an invalid instrument")
    member_keys = [(item.market, item.symbol) for item in snapshot.members]
    if len(set(member_keys)) != len(member_keys):
        raise ProviderDataInvalid("Universe snapshot contains duplicate members")
    return snapshot
