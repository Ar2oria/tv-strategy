"""Bar syncs must invalidate cached indicator results for the instrument."""

from datetime import timedelta

import pytest

from app.db.database import SessionFactory
from app.domain.dto import InstrumentRecord
from app.indicators.models import IndicatorResult
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.services.bar_sync_service import BarSyncService
from app.services.indicator_cache import (
    IndicatorCache,
    indicator_cache_key,
    params_digest,
)
from tests.market_sync_fixtures import TODAY, ScriptedProvider, bar, instrument_dto, market_config


@pytest.fixture
def instrument(session_factory: SessionFactory) -> InstrumentRecord:
    return InstrumentRepository(session_factory).upsert_catalog(instrument_dto())[0]


@pytest.mark.anyio
async def test_successful_sync_invalidates_cached_entries(
    session_factory: SessionFactory,
    instrument: InstrumentRecord,
) -> None:
    cache = IndicatorCache()
    key = indicator_cache_key(
        instrument.id, "1d", "rsi", params_digest({"window": 14})
    )
    cache.store(key, IndicatorResult(), watermark=TODAY)
    assert cache.get(key, watermark=TODAY) is not None

    provider = ScriptedProvider([bar(TODAY)])
    service = BarSyncService(
        BarRepository(session_factory),
        cache=cache,
        today=lambda: TODAY,
        sleep=lambda delay: None,
    )

    outcome = await service.sync_instrument(
        instrument, provider, market_config()
    )

    assert outcome.status == "success"
    assert cache.get(key, watermark=TODAY) is None


@pytest.mark.anyio
async def test_empty_sync_keeps_cached_entries(
    session_factory: SessionFactory,
    instrument: InstrumentRecord,
) -> None:
    cache = IndicatorCache()
    key = indicator_cache_key(
        instrument.id, "1d", "rsi", params_digest({"window": 14})
    )
    cache.store(key, IndicatorResult(), watermark=TODAY)

    provider = ScriptedProvider([])
    service = BarSyncService(
        BarRepository(session_factory),
        cache=cache,
        today=lambda: TODAY,
        sleep=lambda delay: None,
    )

    from app.providers.errors import NoDataAvailable

    with pytest.raises(NoDataAvailable):
        await service.sync_instrument(instrument, provider, market_config())

    assert cache.get(key, watermark=TODAY) is not None
