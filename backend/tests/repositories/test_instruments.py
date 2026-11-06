"""Catalog uniqueness and transactional universe membership tests."""

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.db.database import SessionFactory
from app.domain.dto import InstrumentDTO, UniverseSnapshot
from app.models.instrument import Instrument, UniverseMembership
from app.repositories.instruments import InstrumentRepository


def stock(symbol: str = "AAA", *, name: str = "Alpha") -> InstrumentDTO:
    return InstrumentDTO(
        symbol=symbol,
        name=name,
        market="us_stock",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        instrument_type="stock",
        provider_symbol=symbol,
    )


def related(symbol: str, instrument_type: str) -> InstrumentDTO:
    return replace(
        stock(symbol, name=symbol),
        instrument_type=instrument_type,
        provider_symbol=f"^{symbol}",
    )


def test_instrument_dto_is_frozen() -> None:
    instrument = stock()

    with pytest.raises(FrozenInstanceError):
        instrument.symbol = "BBB"  # type: ignore[misc]


def test_catalog_upsert_preserves_id_and_enforces_market_symbol_unique(
    session_factory: SessionFactory,
) -> None:
    repository = InstrumentRepository(session_factory)
    original = repository.upsert_catalog([stock()])[0]

    updated = repository.upsert_catalog([stock(name="Alpha Updated")])[0]

    assert updated.id == original.id
    assert updated.name == "Alpha Updated"
    assert updated.active is True
    assert repository.get_by_id(original.id) == updated
    assert len(repository.list_instruments()) == 1

    duplicate = {column: getattr(stock(), column) for column in (
        "symbol", "name", "market", "exchange", "currency", "timezone",
        "instrument_type", "provider_symbol",
    )}
    with session_factory() as session:
        with pytest.raises(IntegrityError):
            session.execute(insert(Instrument), duplicate)
            session.flush()
        session.rollback()


def test_universe_replacement_retains_instruments_and_excludes_related(
    session_factory: SessionFactory,
) -> None:
    repository = InstrumentRepository(session_factory)
    first = UniverseSnapshot(
        universe_code="nasdaq100",
        source="first-provider",
        effective_date=date(2025, 1, 2),
        members=(stock("AAA"), stock("BBB", name="Beta")),
        related_instruments=(
            related("NDX", "index"),
            related("SOXX", "etf"),
        ),
    )

    assert repository.replace_universe(first) == (4, 2)
    assert {item.symbol for item in repository.list_members("nasdaq100")} == {
        "AAA", "BBB",
    }
    assert repository.get_by_symbol("us_stock", "NDX") is not None
    assert repository.get_by_symbol("us_stock", "SOXX") is not None

    second = UniverseSnapshot(
        universe_code="nasdaq100",
        source="second-provider",
        effective_date=date(2025, 2, 3),
        members=(stock("BBB", name="Beta"), stock("CCC", name="Gamma")),
        related_instruments=(related("NDX", "index"),),
    )
    assert repository.replace_universe(second) == (3, 2)
    assert {item.symbol for item in repository.list_members("nasdaq100")} == {
        "BBB", "CCC",
    }
    assert repository.get_by_symbol("us_stock", "AAA") is not None
    assert repository.get_by_symbol("us_stock", "SOXX") is not None
    assert len(repository.list_instruments()) == 5

    member_id = repository.get_by_symbol("us_stock", "BBB").id
    with session_factory() as session:
        membership = session.scalar(
            select(UniverseMembership).where(
                UniverseMembership.universe_code == "nasdaq100",
                UniverseMembership.instrument_id == member_id,
            )
        )
        assert membership is not None
        assert membership.source == "second-provider"
        assert membership.effective_date == date(2025, 2, 3)


def test_failed_universe_replacement_rolls_back_catalog_and_membership(
    session_factory: SessionFactory,
) -> None:
    repository = InstrumentRepository(session_factory)
    repository.replace_universe(
        UniverseSnapshot(
            universe_code="nasdaq100",
            source="stable",
            effective_date=date(2025, 1, 2),
            members=(stock("AAA"),),
        )
    )
    invalid = replace(stock("INVALID"), instrument_type="not-a-type")

    with pytest.raises(IntegrityError):
        repository.replace_universe(
            UniverseSnapshot(
                universe_code="nasdaq100",
                source="broken",
                effective_date=date(2025, 1, 3),
                members=(stock("BBB", name="Beta"), invalid),
            )
        )

    assert [item.symbol for item in repository.list_members("nasdaq100")] == [
        "AAA"
    ]
    assert repository.get_by_symbol("us_stock", "BBB") is None
    assert repository.get_by_symbol("us_stock", "INVALID") is None
