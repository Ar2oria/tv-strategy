"""Transactional instrument catalog and universe repository."""

from collections.abc import Iterable

from sqlalchemy import Select, delete, insert, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.database import SessionFactory
from app.domain.dto import InstrumentDTO, InstrumentRecord, Market, UniverseSnapshot
from app.models.instrument import Instrument, UniverseMembership

InstrumentKey = tuple[str, str]


def _key(instrument: InstrumentDTO) -> InstrumentKey:
    return instrument.market, instrument.symbol


def _values(instrument: InstrumentDTO) -> dict[str, object]:
    return {
        "symbol": instrument.symbol,
        "name": instrument.name,
        "market": instrument.market,
        "exchange": instrument.exchange,
        "currency": instrument.currency,
        "timezone": instrument.timezone,
        "instrument_type": instrument.instrument_type,
        "provider_symbol": instrument.provider_symbol,
        "active": True,
    }


def _record(instrument: Instrument) -> InstrumentRecord:
    return InstrumentRecord(
        id=instrument.id,
        active=instrument.active,
        symbol=instrument.symbol,
        name=instrument.name,
        market=instrument.market,
        exchange=instrument.exchange,
        currency=instrument.currency,
        timezone=instrument.timezone,
        instrument_type=instrument.instrument_type,
        provider_symbol=instrument.provider_symbol,
    )


def _upsert_catalog(
    session: Session, instruments: tuple[InstrumentDTO, ...]
) -> list[InstrumentRecord]:
    records: list[InstrumentRecord] = []
    for instrument in instruments:
        statement = sqlite_insert(Instrument).values(**_values(instrument))
        statement = statement.on_conflict_do_update(
            index_elements=["market", "symbol"],
            set_={
                "name": statement.excluded.name,
                "exchange": statement.excluded.exchange,
                "currency": statement.excluded.currency,
                "timezone": statement.excluded.timezone,
                "instrument_type": statement.excluded.instrument_type,
                "provider_symbol": statement.excluded.provider_symbol,
                "active": True,
            },
        )
        session.execute(statement)
        persisted = session.scalar(
            select(Instrument).where(
                Instrument.market == instrument.market,
                Instrument.symbol == instrument.symbol,
            )
        )
        if persisted is None:
            raise RuntimeError(
                f"Instrument upsert returned no row for {_key(instrument)!r}"
            )
        records.append(_record(persisted))
    return records


class InstrumentRepository:
    """Data access boundary for instruments and current memberships."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def upsert_catalog(
        self, instruments: Iterable[InstrumentDTO] | InstrumentDTO
    ) -> list[InstrumentRecord]:
        """Insert or update canonical instruments without replacing their IDs."""
        items = (
            (instruments,)
            if isinstance(instruments, InstrumentDTO)
            else tuple(instruments)
        )
        with self._sessions() as session:
            with session.begin():
                return _upsert_catalog(session, items)

    def replace_universe(self, snapshot: UniverseSnapshot) -> tuple[int, int]:
        """Atomically replace members while retaining all instrument rows."""
        if not isinstance(snapshot, UniverseSnapshot):
            raise TypeError("snapshot must be a UniverseSnapshot")
        catalog: dict[InstrumentKey, InstrumentDTO] = {}
        for instrument in (*snapshot.related_instruments, *snapshot.members):
            catalog[_key(instrument)] = instrument
        member_keys = tuple(dict.fromkeys(_key(item) for item in snapshot.members))

        with self._sessions() as session:
            with session.begin():
                records = _upsert_catalog(session, tuple(catalog.values()))
                ids = {_key(record): record.id for record in records}
                session.execute(
                    delete(UniverseMembership).where(
                        UniverseMembership.universe_code == snapshot.universe_code
                    )
                )
                rows = [
                    {
                        "universe_code": snapshot.universe_code,
                        "instrument_id": ids[key],
                        "source": snapshot.source,
                        "effective_date": snapshot.effective_date,
                    }
                    for key in member_keys
                ]
                if rows:
                    session.execute(insert(UniverseMembership), rows)
        return len(catalog), len(member_keys)

    def get_by_id(self, instrument_id: int) -> InstrumentRecord | None:
        with self._sessions() as session:
            instrument = session.get(Instrument, instrument_id)
            return None if instrument is None else _record(instrument)

    def get(self, instrument_id: int) -> InstrumentRecord | None:
        """Alias for consumers that use repository-standard get terminology."""
        return self.get_by_id(instrument_id)

    def get_by_symbol(
        self, market: Market, symbol: str
    ) -> InstrumentRecord | None:
        with self._sessions() as session:
            instrument = session.scalar(
                select(Instrument).where(
                    Instrument.market == market,
                    Instrument.symbol == symbol,
                )
            )
            return None if instrument is None else _record(instrument)

    def list_instruments(
        self,
        *,
        market: Market | None = None,
        universe_code: str | None = None,
        query: str | None = None,
        active: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[InstrumentRecord]:
        """List detached records with optional parameterized filters."""
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must not be negative")
        statement: Select[tuple[Instrument]] = select(Instrument)
        if universe_code is not None:
            statement = statement.join(UniverseMembership).where(
                UniverseMembership.universe_code == universe_code
            )
        if market is not None:
            statement = statement.where(Instrument.market == market)
        if active is not None:
            statement = statement.where(Instrument.active == active)
        if query:
            statement = statement.where(
                or_(
                    Instrument.symbol.contains(query, autoescape=True),
                    Instrument.name.contains(query, autoescape=True),
                    Instrument.provider_symbol.contains(query, autoescape=True),
                )
            )
        statement = statement.order_by(Instrument.symbol, Instrument.id).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        with self._sessions() as session:
            return [_record(item) for item in session.scalars(statement).all()]

    def list_members(
        self, universe_code: str, *, market: Market | None = None
    ) -> list[InstrumentRecord]:
        """Return constituents only; related instruments are not included."""
        return self.list_instruments(
            market=market, universe_code=universe_code
        )

    def search(
        self,
        query: str,
        *,
        market: Market | None = None,
        universe_code: str | None = None,
        limit: int = 50,
    ) -> list[InstrumentRecord]:
        return self.list_instruments(
            market=market,
            universe_code=universe_code,
            query=query,
            active=True,
            limit=limit,
        )

    def list_universes(self) -> list[str]:
        """Return stable universe codes in lexical order."""
        statement = (
            select(UniverseMembership.universe_code).distinct().order_by(
                UniverseMembership.universe_code
            )
        )
        with self._sessions() as session:
            return list(session.scalars(statement).all())
