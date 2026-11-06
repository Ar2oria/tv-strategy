"""Service regressions for concealed numeric and container parameter values."""

from collections import deque
from collections.abc import Sequence
from datetime import date

import pytest
from pydantic import BaseModel, field_serializer, field_validator

from app.db.database import SessionFactory
from app.domain.dto import BarDTO
from app.indicators.base import IndicatorContext, IndicatorParams
from app.indicators.models import IndicatorResult
from app.indicators.registry import IndicatorRegistry
from tests.services.test_indicator_service import (
    build_service,
    compute_request,
    daily_bar,
    instance,
    make_test_indicator,
)


@pytest.mark.parametrize(
    "produced_value",
    [
        complex(float("inf"), 0),
        deque([float("inf")]),
    ],
    ids=["complex-infinity", "deque-infinity"],
)
def test_serializer_cannot_conceal_complex_or_deque_values_from_calculation(
    session_factory: SessionFactory,
    produced_value: object,
) -> None:
    class ConcealedContainerParams(IndicatorParams):
        value: object = None

        @field_validator("value")
        @classmethod
        def produce_non_finite_value(cls, value: object) -> object:
            return produced_value if value == 13.0 else value

        @field_serializer("value")
        def conceal_actual_value(self, value: object) -> str:
            return "concealed"

    calls: list[BaseModel] = []

    def calculate(
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        validated: BaseModel,
    ) -> IndicatorResult:
        calls.append(validated)
        return IndicatorResult()

    indicator = make_test_indicator("concealed-container", calculate)
    indicator.params_model = ConcealedContainerParams
    registry = IndicatorRegistry()
    registry.register(indicator)
    service, instrument_id = build_service(
        session_factory,
        [daily_bar(date(2026, 1, 1))],
        registry,
    )

    result = service.compute(
        compute_request(
            instrument_id,
            (
                instance(
                    "concealed-container",
                    "concealed-container",
                    {"value": 13.0},
                ),
            ),
        )
    )[0]

    assert result.error == "Invalid indicator parameters"
    assert result.series == ()
    assert calls == []
