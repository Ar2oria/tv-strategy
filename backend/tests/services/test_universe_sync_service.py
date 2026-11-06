"""Complete-snapshot universe synchronization with failure preservation."""

import threading
from datetime import date

import pytest

from app.db.database import SessionFactory
from app.domain.dto import UniverseSnapshot
from app.providers.errors import ProviderDataInvalid, ProviderUnavailable
from app.repositories.instruments import InstrumentRepository
from app.services.universe_sync_service import UniverseSyncService
from tests.market_sync_fixtures import instrument_dto


class UniverseProvider:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[str] = []
        self.thread_ids: list[int] = []

    def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
        self.calls.append(universe_code)
        self.thread_ids.append(threading.get_ident())
        if isinstance(self.response, Exception):
            raise self.response
        return self.response  # type: ignore[return-value]


def snapshot(code: str = "nasdaq100", symbol: str = "AAA") -> UniverseSnapshot:
    return UniverseSnapshot(
        universe_code=code,
        source="fixture",
        effective_date=date(2026, 1, 30),
        members=(instrument_dto(symbol),),
    )


@pytest.mark.anyio
async def test_complete_snapshot_is_fetched_before_atomic_replacement(
    session_factory: SessionFactory,
) -> None:
    repository = InstrumentRepository(session_factory)
    repository.replace_universe(snapshot(symbol="OLD"))
    provider = UniverseProvider(snapshot(symbol="NEW"))
    service = UniverseSyncService(repository)

    outcome = await service.sync_universe("nasdaq100", provider)

    assert outcome.universe_code == "nasdaq100"
    assert outcome.member_count == 1
    assert outcome.instrument_count == 1
    assert [item.symbol for item in repository.list_members("nasdaq100")] == ["NEW"]
    assert provider.calls == ["nasdaq100"]
    assert provider.thread_ids != [threading.get_ident()]


@pytest.mark.anyio
async def test_failed_refresh_preserves_existing_membership(
    session_factory: SessionFactory,
) -> None:
    repository = InstrumentRepository(session_factory)
    repository.replace_universe(snapshot(symbol="OLD"))
    provider = UniverseProvider(ProviderUnavailable("private upstream"))
    service = UniverseSyncService(repository)

    with pytest.raises(ProviderUnavailable):
        await service.sync_universe("nasdaq100", provider)

    assert [item.symbol for item in repository.list_members("nasdaq100")] == ["OLD"]


@pytest.mark.anyio
async def test_mismatched_or_malformed_snapshot_never_replaces_membership(
    session_factory: SessionFactory,
) -> None:
    repository = InstrumentRepository(session_factory)
    repository.replace_universe(snapshot(symbol="OLD"))
    provider = UniverseProvider(snapshot(code="soxx", symbol="NEW"))
    service = UniverseSyncService(repository)

    with pytest.raises(ProviderDataInvalid):
        await service.sync_universe("nasdaq100", provider)

    assert [item.symbol for item in repository.list_members("nasdaq100")] == ["OLD"]
