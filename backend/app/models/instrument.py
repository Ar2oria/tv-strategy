"""Instrument catalog and current universe membership tables."""

from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, String
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.dto import InstrumentType, Market

MARKET_CHECK = "market IN ('a_share', 'hk_stock', 'us_stock', 'crypto')"
INSTRUMENT_TYPE_CHECK = (
    "instrument_type IN ('stock', 'index', 'etf', 'crypto_spot')"
)


class Instrument(Base):
    """Canonical instrument keyed by market and provider-neutral symbol."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint(
            "market", "symbol", name="uq_instruments_market_symbol"
        ),
        CheckConstraint(MARKET_CHECK, name="valid_market"),
        CheckConstraint(INSTRUMENT_TYPE_CHECK, name="valid_instrument_type"),
        Index("ix_instruments_market_active", "market", "active"),
        Index("ix_instruments_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    market: Mapped[Market] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_type: Mapped[InstrumentType] = mapped_column(
        String(32), nullable=False
    )
    provider_symbol: Mapped[str] = mapped_column(String(256), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )


class UniverseMembership(Base):
    """Membership metadata for one current universe snapshot."""

    __tablename__ = "universe_memberships"
    __table_args__ = (
        UniqueConstraint(
            "universe_code",
            "instrument_id",
            name="uq_universe_memberships_universe_instrument",
        ),
        Index("ix_universe_memberships_instrument_id", "instrument_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    universe_code: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
