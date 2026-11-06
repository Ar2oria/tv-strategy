"""Cooperative timeout preservation for current-universe replacement."""

import asyncio
import threading
from datetime import date

import pytest

from app.db.database import SessionFactory
from app.domain.dto import UniverseSnapshot
from app.providers.errors import ProviderUnavailable
from app.repositories.instruments import InstrumentRepository
from app.services.universe_sync_service import UniverseSyncService
from tests.market_sync_fixtures import instrument_dto


def snapshot(symbol: str) -> UniverseSnapshot:
    return UniverseSnapshot(
        universe_code="nasdaq100",
        source="fixture",
        effective_date=date(2026, 1, 30),
        members=(instrument_dto(symbol),),
    )


@pytest.mark.anyio
async def test_cooperative_universe_timeout_preserves_membership_and_ignores_late_result(
    session_factory: SessionFactory,
) -> None:
    repository = InstrumentRepository(session_factory)
    repository.replace_universe(snapshot("OLD"))
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingProvider:
        def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
            started.set()
            release.wait(2.0)
            finished.set()
            return snapshot("NEW")

    task = asyncio.create_task(
        UniverseSyncService(repository).sync_universe(
            "nasdaq100",
            BlockingProvider(),
            timeout=0.01,
        )
    )
    assert await asyncio.to_thread(started.wait, 1.0)
    try:
        with pytest.raises(ProviderUnavailable) as captured:
            await task
        assert "cooperative" in (captured.value.detail or "").casefold()
    finally:
        release.set()
    assert await asyncio.to_thread(finished.wait, 1.0)
    await asyncio.sleep(0)
    assert [item.symbol for item in repository.list_members("nasdaq100")] == ["OLD"]
