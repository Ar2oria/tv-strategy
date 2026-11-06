"""Batch indicator history, trimming, limits, and failure-isolation tests."""

import logging
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import ClassVar

import pytest
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.api.schemas import IndicatorComputeRequest, IndicatorInstanceRequest
from app.config.defaults import default_settings
from app.config.models import IndicatorSettings, Settings
from app.db.database import SessionFactory
from app.domain.dto import BarDTO, InstrumentDTO, Timeframe
from app.indicators.base import Indicator, IndicatorContext, IndicatorParams
from app.indicators.builtin.rsi import RSIIndicator, RSIParams
from app.indicators.models import (
    IndicatorResult,
    MarkerDefinition,
    PaneDefinition,
    ReferenceLine,
    SeriesDefinition,
    SeriesPoint,
)
from app.indicators.registry import IndicatorDescriptor, IndicatorRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.services.bar_service import BarService, InstrumentNotFoundError
from app.services.indicator_cache import IndicatorCache
from app.services.indicator_service import (
    IndicatorRequestError,
    IndicatorService,
)

Behavior = Callable[[IndicatorContext, Sequence[BarDTO], BaseModel], IndicatorResult]


def daily_bar(day: date, close: float = 11.0) -> BarDTO:
    return BarDTO(
        time=day,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=100.0,
        source="fixture",
        adjustment="qfq",
    )


def line_result(bars: Sequence[BarDTO]) -> IndicatorResult:
    return IndicatorResult(
        panes=(PaneDefinition(id="panel", title="Panel"),),
        series=(
            SeriesDefinition(
                id="value",
                pane_id="panel",
                type="line",
                title="Value",
                points=tuple(
                    SeriesPoint(time=bar.time, value=float(index))
                    for index, bar in enumerate(bars)
                ),
            ),
        ),
    )


def make_test_indicator(name: str, behavior: Behavior) -> type[Indicator]:
    class TestIndicator(Indicator):
        indicator_name: ClassVar[str] = name
        params_model: ClassVar[type[BaseModel]] = IndicatorParams

        def calculate(
            self,
            context: IndicatorContext,
            bars: Sequence[BarDTO],
            params: BaseModel,
        ) -> IndicatorResult:
            return behavior(context, bars, params)

    TestIndicator.name = name
    TestIndicator.display_name = name.title()
    TestIndicator.description = f"{name} test indicator"
    return TestIndicator


def configured_settings(**values: int) -> Settings:
    return default_settings().model_copy(
        update={"indicators": IndicatorSettings(**values)}
    )


def compute_request(
    instrument_id: int,
    indicators: tuple[IndicatorInstanceRequest, ...],
    *,
    start: date = date(2026, 1, 1),
    end: date = date(2026, 12, 31),
    timeframe: Timeframe = "1d",
) -> IndicatorComputeRequest:
    return IndicatorComputeRequest(
        instrument_id=instrument_id,
        timeframe=timeframe,
        start=start,
        end=end,
        indicators=indicators,
    )


def instance(
    instance_id: str,
    name: str,
    params: dict[str, object] | None = None,
) -> IndicatorInstanceRequest:
    return IndicatorInstanceRequest(
        instance_id=instance_id,
        name=name,
        params={} if params is None else params,
    )


def build_service(
    factory: SessionFactory,
    bars: Sequence[BarDTO],
    registry: IndicatorRegistry,
    *,
    settings: Settings | None = None,
    bar_service: BarService | None = None,
    cache: IndicatorCache | None = None,
) -> tuple[IndicatorService, int]:
    instruments = InstrumentRepository(factory)
    instrument_id = instruments.upsert_catalog(
        InstrumentDTO(
            symbol="AAA",
            name="Alpha",
            market="us_stock",
            exchange="NASDAQ",
            currency="USD",
            timezone="America/New_York",
            instrument_type="stock",
            provider_symbol="AAA",
        )
    )[0].id
    BarRepository(factory).upsert(instrument_id, bars)
    service = IndicatorService(
        bar_service=bar_service or BarService(BarRepository(factory), instruments),
        instruments=instruments,
        registry=registry,
        settings=settings or default_settings(),
        cache=cache,
    )
    return service, instrument_id


def test_rsi_uses_earlier_history_but_trims_points_before_visible_monday(
    session_factory: SessionFactory,
) -> None:
    days = [date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14)]
    closes = [10.0, 11.0, 12.0, 11.5, 12.5, 13.0, 12.0, 14.0]
    bars = [daily_bar(day, close) for day, close in zip(days, closes, strict=True)]
    registry = IndicatorRegistry()
    registry.register(RSIIndicator)
    service, instrument_id = build_service(session_factory, bars, registry)
    monday = date(2026, 1, 12)

    computations = service.compute(
        compute_request(
            instrument_id,
            (instance("rsi-visible", "rsi", {"window": 2}),),
            start=monday,
            end=date(2026, 1, 14),
        )
    )

    full = RSIIndicator().calculate(
        IndicatorContext(symbol="AAA", start=monday, end=date(2026, 1, 14)),
        bars,
        RSIParams(window=2),
    )
    expected = tuple(point for point in full.series[0].points if point.time >= monday)
    assert computations[0].error is None
    assert computations[0].series[0].points == expected
    assert computations[0].series[0].points[0].time == monday
    assert all(point.time >= monday for point in computations[0].series[0].points)


def test_two_rsi_instances_have_distinct_namespaced_ids(
    session_factory: SessionFactory,
) -> None:
    bars = [daily_bar(date(2026, 1, 1) + timedelta(days=i), 10.0 + i) for i in range(8)]
    registry = IndicatorRegistry()
    registry.register(RSIIndicator)
    service, instrument_id = build_service(session_factory, bars, registry)

    results = service.compute(
        compute_request(
            instrument_id,
            (
                instance("rsi-fast", "rsi", {"window": 2}),
                instance("rsi-slow", "rsi", {"window": 3}),
            ),
        )
    )

    assert [result.series[0].id for result in results] == ["rsi-fast:rsi", "rsi-slow:rsi"]
    assert results[0].panes[0].id == "rsi-fast:rsi"
    assert results[1].panes[0].id == "rsi-slow:rsi"
    assert results[0].series[0].title == "RSI (2)"
    assert results[1].series[0].title == "RSI (3)"


def test_one_failure_preserves_other_results_and_each_input_is_fresh(
    session_factory: SessionFactory,
) -> None:
    received: list[Sequence[BarDTO]] = []

    def explode(context: IndicatorContext, bars: Sequence[BarDTO], params: BaseModel) -> IndicatorResult:
        received.append(bars)
        raise RuntimeError("private database password")

    def succeed(context: IndicatorContext, bars: Sequence[BarDTO], params: BaseModel) -> IndicatorResult:
        received.append(bars)
        assert context.symbol == "AAA"
        return line_result(bars)

    registry = IndicatorRegistry()
    registry.register(make_test_indicator("explode", explode))
    registry.register(make_test_indicator("succeed", succeed))
    bars = [daily_bar(date(2026, 1, 1) + timedelta(days=i), 10.0 + i) for i in range(5)]

    class CountingBarService(BarService):
        def __init__(self) -> None:
            super().__init__(
                BarRepository(session_factory), InstrumentRepository(session_factory)
            )
            self.history_calls = 0

        def get_history_until(self, instrument_id: int, end: date, timeframe: Timeframe = "1d") -> list[BarDTO]:
            self.history_calls += 1
            return super().get_history_until(instrument_id, end, timeframe)

    counting = CountingBarService()
    service, instrument_id = build_service(
        session_factory,
        bars,
        registry,
        bar_service=counting,
    )

    results = service.compute(
        compute_request(
            instrument_id,
            (instance("bad", "explode"), instance("good", "succeed")),
        )
    )

    assert results[0].error == "Indicator calculation failed"
    assert results[0].series == ()
    assert results[1].error is None
    assert len(results[1].series[0].points) == 5
    assert results[1].series[0].id == "good:value"
    assert counting.history_calls == 1
    assert len(received) == 2
    assert received[0] is not received[1]
    assert "private database password" not in repr(results)


def test_active_indicator_limit_is_enforced_before_calculation(
    session_factory: SessionFactory,
) -> None:
    registry = IndicatorRegistry()
    registry.register(make_test_indicator("good", lambda context, bars, params: line_result(bars)))
    service, instrument_id = build_service(
        session_factory,
        [daily_bar(date(2026, 1, 1))],
        registry,
        settings=configured_settings(max_active_indicators=1),
    )

    with pytest.raises(IndicatorRequestError, match="maximum is 1"):
        service.compute(
            compute_request(
                instrument_id,
                (instance("one", "good"), instance("two", "good")),
            )
        )


def test_large_outputs_are_no_longer_capped(
    session_factory: SessionFactory,
) -> None:
    """The max_points_per_indicator limit was removed; big outputs pass."""
    registry = IndicatorRegistry()
    registry.register(make_test_indicator("large", lambda context, bars, params: line_result(bars)))
    bars = [daily_bar(date(2026, 1, 1) + timedelta(days=i)) for i in range(101)]
    service, instrument_id = build_service(
        session_factory,
        bars,
        registry,
    )

    results = service.compute(
        compute_request(instrument_id, (instance("large", "large"),))
    )

    assert results[0].error is None
    assert len(results[0].series[0].points) == 101


def test_invalid_parameters_do_not_block_another_instance(
    session_factory: SessionFactory,
) -> None:
    registry = IndicatorRegistry()
    registry.register(RSIIndicator)
    bars = [daily_bar(date(2026, 1, 1) + timedelta(days=i), 10.0 + i) for i in range(8)]
    service, instrument_id = build_service(session_factory, bars, registry)

    results = service.compute(
        compute_request(
            instrument_id,
            (
                instance("invalid", "rsi", {"window": 0}),
                instance("valid", "rsi", {"window": 2}),
            ),
        )
    )

    assert results[0].error == "Invalid indicator parameters"
    assert results[0].series == ()
    assert results[1].error is None


@pytest.mark.parametrize(
    "params",
    [
        {"unexpected": 1},
        {"nested": {"unexpected": 1}},
        {"value": float("nan")},
        {"nested": {"value": float("inf")}},
        {"nested": {"value": float("-inf")}},
    ],
    ids=[
        "top-level-unknown",
        "nested-unknown",
        "nan",
        "positive-infinity",
        "negative-infinity",
    ],
)
def test_unknown_and_non_finite_params_fail_before_calculation(
    session_factory: SessionFactory,
    params: dict[str, object],
) -> None:
    class NestedParams(IndicatorParams):
        value: float = 1.0

    class CustomParams(IndicatorParams):
        value: float = 1.0
        nested: NestedParams = Field(default_factory=NestedParams)

    calls: list[BaseModel] = []

    def calculate(
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        validated: BaseModel,
    ) -> IndicatorResult:
        calls.append(validated)
        return IndicatorResult()

    indicator = make_test_indicator("strict-params", calculate)
    indicator.params_model = CustomParams
    registry = IndicatorRegistry()
    registry.register(indicator)
    service, instrument_id = build_service(
        session_factory, [daily_bar(date(2026, 1, 1))], registry
    )

    result = service.compute(
        compute_request(
            instrument_id,
            (instance("strict-params", "strict-params", params),),
        )
    )[0]

    assert result.error == "Invalid indicator parameters"
    assert result.series == ()
    assert calls == []


def test_non_finite_values_produced_by_validation_fail_before_calculation(
    session_factory: SessionFactory,
) -> None:
    class OverflowParams(IndicatorParams):
        value: float = 1.0

        @field_validator("value")
        @classmethod
        def produce_infinity(cls, value: float) -> float:
            return float("inf") if value == 13.0 else value

    calls: list[BaseModel] = []

    def calculate(
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        validated: BaseModel,
    ) -> IndicatorResult:
        calls.append(validated)
        return IndicatorResult()

    indicator = make_test_indicator("overflow-params", calculate)
    indicator.params_model = OverflowParams
    registry = IndicatorRegistry()
    registry.register(indicator)
    service, instrument_id = build_service(
        session_factory, [daily_bar(date(2026, 1, 1))], registry
    )

    result = service.compute(
        compute_request(
            instrument_id,
            (
                instance(
                    "overflow-params",
                    "overflow-params",
                    {"value": 13.0},
                ),
            ),
        )
    )[0]

    assert result.error == "Invalid indicator parameters"
    assert calls == []


def test_serializer_cannot_conceal_non_finite_parameters_from_calculation_guard(
    session_factory: SessionFactory,
) -> None:
    class ConcealedInfinityParams(IndicatorParams):
        value: float = 1.0

        @field_validator("value")
        @classmethod
        def produce_infinity(cls, value: float) -> float:
            return float("inf") if value == 13.0 else value

        @field_serializer("value")
        def conceal_infinity(self, value: float) -> str | float:
            return "inf" if value == float("inf") else value

    calls: list[BaseModel] = []

    def calculate(
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        validated: BaseModel,
    ) -> IndicatorResult:
        calls.append(validated)
        return IndicatorResult()

    indicator = make_test_indicator("concealed-infinity", calculate)
    indicator.params_model = ConcealedInfinityParams
    registry = IndicatorRegistry()
    registry.register(indicator)
    service, instrument_id = build_service(
        session_factory, [daily_bar(date(2026, 1, 1))], registry
    )

    result = service.compute(
        compute_request(
            instrument_id,
            (
                instance(
                    "concealed-infinity",
                    "concealed-infinity",
                    {"value": 13.0},
                ),
            ),
        )
    )[0]

    assert result.error == "Invalid indicator parameters"
    assert result.series == ()
    assert calls == []


def test_unexpected_descriptor_failure_is_logged_and_isolated(
    session_factory: SessionFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private descriptor registry secret"

    class FlakyRegistry(IndicatorRegistry):
        def get(self, name: str) -> IndicatorDescriptor:
            if name == "broken-registry":
                raise RuntimeError(secret)
            return super().get(name)

    registry = FlakyRegistry()
    registry.register(
        make_test_indicator("healthy", lambda context, bars, params: line_result(bars))
    )
    service, instrument_id = build_service(
        session_factory, [daily_bar(date(2026, 1, 1))], registry
    )

    with caplog.at_level(logging.ERROR, logger="app.services.indicator_service"):
        results = service.compute(
            compute_request(
                instrument_id,
                (
                    instance("broken-registry", "broken-registry"),
                    instance("healthy", "healthy"),
                ),
            )
        )

    assert results[0].error == "Indicator calculation failed"
    assert results[0].series == ()
    assert results[1].error is None
    assert len(results[1].series[0].points) == 1
    assert secret not in repr(results)
    assert "broken-registry" in caplog.text
    assert secret in caplog.text


def test_unexpected_parameter_validator_failure_is_logged_and_isolated(
    session_factory: SessionFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private parameter validator secret"

    class RuntimeErrorParams(IndicatorParams):
        @model_validator(mode="after")
        def fail_unexpectedly(self) -> "RuntimeErrorParams":
            raise RuntimeError(secret)

    broken = make_test_indicator(
        "broken-params", lambda context, bars, params: IndicatorResult()
    )
    broken.params_model = RuntimeErrorParams
    registry = IndicatorRegistry()
    registry.register(broken)
    registry.register(
        make_test_indicator("healthy", lambda context, bars, params: line_result(bars))
    )
    service, instrument_id = build_service(
        session_factory, [daily_bar(date(2026, 1, 1))], registry
    )

    with caplog.at_level(logging.ERROR, logger="app.services.indicator_service"):
        results = service.compute(
            compute_request(
                instrument_id,
                (
                    instance("broken-params", "broken-params"),
                    instance("healthy", "healthy"),
                ),
            )
        )

    assert results[0].error == "Invalid indicator parameters"
    assert results[0].series == ()
    assert results[1].error is None
    assert len(results[1].series[0].points) == 1
    assert secret not in repr(results)
    assert "broken-params" in caplog.text
    assert secret in caplog.text


def unsafe_point(day: date, value: object = 1.0) -> SeriesPoint:
    return SeriesPoint.model_construct(time=day, value=value, color=None)


def unsafe_result(points: tuple[SeriesPoint, ...]) -> IndicatorResult:
    series = SeriesDefinition.model_construct(
        id="value",
        pane_id="main",
        type="line",
        title="Unsafe",
        points=points,
        color="#2962ff",
    )
    return IndicatorResult.model_construct(series=(series,))


@pytest.mark.parametrize(
    "points",
    [
        (unsafe_point(date(2026, 1, 1)), unsafe_point(date(2026, 1, 1))),
        (unsafe_point(date(2026, 1, 3)), unsafe_point(date(2026, 1, 1))),
        (unsafe_point(date(2026, 1, 1), float("nan")),),
        (unsafe_point(date(2026, 1, 1), float("inf")),),
        (unsafe_point(date(2026, 1, 1), float("-inf")),),
        (unsafe_point(date(2026, 1, 1), None),),
        (unsafe_point(date(2026, 1, 2)),),
    ],
    ids=["duplicate", "unsorted", "nan", "infinity", "negative-infinity", "null", "misaligned"],
)
def test_invalid_indicator_outputs_are_isolated(
    session_factory: SessionFactory,
    points: tuple[SeriesPoint, ...],
) -> None:
    registry = IndicatorRegistry()
    registry.register(make_test_indicator("unsafe", lambda context, bars, params: unsafe_result(points)))
    registry.register(make_test_indicator("safe", lambda context, bars, params: line_result(bars)))
    bars = [daily_bar(date(2026, 1, 1)), daily_bar(date(2026, 1, 3))]
    service, instrument_id = build_service(session_factory, bars, registry)

    results = service.compute(
        compute_request(
            instrument_id,
            (instance("unsafe", "unsafe"), instance("safe", "safe")),
            end=date(2026, 1, 3),
        )
    )

    assert results[0].error == "Indicator output validation failed"
    assert results[0].series == ()
    assert results[1].error is None
    assert len(results[1].series[0].points) == 2


def test_non_result_return_value_is_also_isolated(
    session_factory: SessionFactory,
) -> None:
    registry = IndicatorRegistry()
    registry.register(
        make_test_indicator("wrong-type", lambda context, bars, params: None)
    )
    registry.register(
        make_test_indicator("safe", lambda context, bars, params: line_result(bars))
    )
    service, instrument_id = build_service(
        session_factory, [daily_bar(date(2026, 1, 1))], registry
    )

    results = service.compute(
        compute_request(
            instrument_id,
            (instance("wrong-type", "wrong-type"), instance("safe", "safe")),
        )
    )

    assert results[0].error == "Indicator output validation failed"
    assert results[0].series == ()
    assert results[1].error is None
    assert len(results[1].series[0].points) == 1


def test_compute_rejects_missing_instrument(session_factory: SessionFactory) -> None:
    registry = IndicatorRegistry()
    service = IndicatorService(
        bar_service=BarService(BarRepository(session_factory), InstrumentRepository(session_factory)),
        instruments=InstrumentRepository(session_factory),
        registry=registry,
        settings=default_settings(),
    )

    with pytest.raises(InstrumentNotFoundError):
        service.compute(compute_request(999, ()))


class CountingCache(IndicatorCache):
    """Test double counting stores routed through the cache."""

    def __init__(self) -> None:
        super().__init__()
        self.stores: list[tuple[int, str, str, str]] = []

    def store(self, key, result, *, watermark):
        self.stores.append(key)
        return super().store(key, result, watermark=watermark)


def test_cached_second_call_skips_recalculation(
    session_factory: SessionFactory,
) -> None:
    calls = {"count": 0}

    def counted(context, bars, params):
        calls["count"] += 1
        return line_result(bars)

    registry = IndicatorRegistry()
    registry.register(make_test_indicator("counter", counted))
    cache = CountingCache()
    service, instrument_id = build_service(
        session_factory,
        [daily_bar(date(2026, 1, day)) for day in range(1, 10)],
        registry,
        cache=cache,
    )

    first = service.compute(
        compute_request(
            instrument_id,
            (instance("one", "counter"),),
            start=date(2026, 1, 5),
            end=date(2026, 1, 9),
        )
    )
    second = service.compute(
        compute_request(
            instrument_id,
            (instance("one", "counter"),),
            start=date(2026, 1, 3),
            end=date(2026, 1, 9),
        )
    )

    assert calls["count"] == 1
    assert first[0].error is None
    assert second[0].error is None
    assert len(first[0].series[0].points) == 5
    assert len(second[0].series[0].points) == 7
    assert len(cache.stores) == 1

def test_open_ended_request_defaults_to_full_history(
    session_factory: SessionFactory,
) -> None:
    bars = [daily_bar(date(2026, 1, day)) for day in range(1, 10)]
    registry = IndicatorRegistry()
    registry.register(
        make_test_indicator("line", lambda context, bars, params: line_result(bars))
    )
    service, instrument_id = build_service(session_factory, bars, registry)

    results = service.compute(
        IndicatorComputeRequest(
            instrument_id=instrument_id,
            timeframe="1d",
            indicators=(instance("all", "line"),),
        )
    )

    assert results[0].error is None
    assert len(results[0].series[0].points) == 9

def test_end_only_request_returns_tail_slice(
    session_factory: SessionFactory,
) -> None:
    bars = [daily_bar(date(2026, 1, day)) for day in range(1, 10)]
    registry = IndicatorRegistry()
    registry.register(
        make_test_indicator("line", lambda context, bars, params: line_result(bars))
    )
    service, instrument_id = build_service(session_factory, bars, registry)

    results = service.compute(
        IndicatorComputeRequest(
            instrument_id=instrument_id,
            timeframe="1d",
            end=date(2026, 1, 7),
            limit=3,
            indicators=(instance("tail", "line"),),
        )
    )

    assert results[0].error is None
    points = results[0].series[0].points
    assert [point.time.day for point in points] == [5, 6, 7]

def test_different_params_are_cached_separately(
    session_factory: SessionFactory,
) -> None:
    calls = {"count": 0}

    class CountingRSI(RSIIndicator):
        def calculate(self, context, bars, params):
            calls["count"] += 1
            return super().calculate(context, bars, params)

    registry = IndicatorRegistry()
    registry.register(CountingRSI)
    service, instrument_id = build_service(
        session_factory,
        [daily_bar(date(2026, 1, day)) for day in range(1, 10)],
        registry,
        cache=IndicatorCache(),
    )

    for identifier, window in (("a", 2), ("b", 5), ("c", 2)):
        result = service.compute(
            compute_request(
                instrument_id,
                (instance(identifier, "rsi", {"window": window}),),
                start=date(2026, 1, 1),
                end=date(2026, 1, 9),
            )
        )
        assert result[0].error is None

    assert calls["count"] == 2
