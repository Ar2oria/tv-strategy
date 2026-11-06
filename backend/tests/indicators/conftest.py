"""Shared immutable bar factory for indicator tests."""

from collections.abc import Callable
from datetime import date

import pytest

from app.domain.dto import BarDTO


@pytest.fixture
def bar_factory() -> Callable[..., BarDTO]:
    """Build normalized daily bars without sharing mutable state."""

    def make_bar(
        day: int,
        close: float,
        *,
        high: float | None = None,
        low: float | None = None,
    ) -> BarDTO:
        return BarDTO(
            time=date(2026, 1, day),
            open=close,
            high=close + 1 if high is None else high,
            low=close - 1 if low is None else low,
            close=close,
            volume=1_000.0,
            source="test",
            adjustment="none",
        )

    return make_bar
