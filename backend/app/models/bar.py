"""Daily OHLCV persistence model."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Index, String
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utc_now
from app.domain.dto import Adjustment

ADJUSTMENT_CHECK = "adjustment IN ('qfq', 'none')"


class DailyBar(Base):
    """One provider-adjusted daily bar per instrument and trading date."""

    __tablename__ = "daily_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "date", name="uq_daily_bars_instrument_date"
        ),
        CheckConstraint(ADJUSTMENT_CHECK, name="valid_adjustment"),
        Index("ix_daily_bars_date", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    adjustment: Mapped[Adjustment] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )
