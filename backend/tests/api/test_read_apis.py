"""Isolated FastAPI tests for catalog, bars, descriptors, and batch compute."""

import asyncio
from collections.abc import Iterator, Sequence
from datetime import date
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator

from app.api.bars import router as bars_router
from app.api.indicators import router as indicators_router
from app.api.instruments import router as instruments_router
from app.api.responses import register_response_handlers
from app.config.defaults import default_settings
from app.config.models import Settings
from app.db.database import SessionFactory
from app.domain.dto import BarDTO, InstrumentDTO, UniverseSnapshot
from app.indicators.base import Indicator, IndicatorContext, IndicatorParams
from app.indicators.builtin.rsi import RSIIndicator
from app.indicators.models import IndicatorResult
from app.indicators.registry import IndicatorRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.services.bar_service import BarService
from app.services.indicator_service import IndicatorService

API_ROOT = "/api/v1"


class ExplodingIndicator(Indicator):
    name: ClassVar[str] = "explode"
    display_name: ClassVar[str] = "Exploding test indicator"
    description: ClassVar[str] = "Always raises a private test exception"
    params_model: ClassVar[type[BaseModel]] = IndicatorParams

    def calculate(
        self,
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        params: BaseModel,
    ) -> IndicatorResult:
        raise RuntimeError("private database password")


class RuntimeErrorParams(IndicatorParams):
    @model_validator(mode="after")
    def fail_unexpectedly(self) -> "RuntimeErrorParams":
        raise RuntimeError("private parameter validator secret")


class ParameterExplodingIndicator(Indicator):
    name: ClassVar[str] = "parameter-explode"
    display_name: ClassVar[str] = "Parameter exploding test indicator"
    description: ClassVar[str] = "Raises unexpectedly during parameter validation"
    params_model: ClassVar[type[BaseModel]] = RuntimeErrorParams

    def calculate(
        self,
        context: IndicatorContext,
        bars: Sequence[BarDTO],
        params: BaseModel,
    ) -> IndicatorResult:
        return IndicatorResult()


def stock(symbol: str, name: str) -> InstrumentDTO:
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


def bar(day: date, close: float) -> BarDTO:
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


def seed_database(factory: SessionFactory) -> int:
    instruments = InstrumentRepository(factory)
    instruments.replace_universe(
        UniverseSnapshot(
            universe_code="nasdaq100",
            source="fixture",
            effective_date=date(2026, 1, 1),
            members=(stock("AAA", "Alpha"), stock("BBB", "Beta")),
        )
    )
    record = instruments.get_by_symbol("us_stock", "AAA")
    assert record is not None
    bars = [
        bar(day, close)
        for day, close in (
            (date(2026, 1, 5), 11.0),
            (date(2026, 1, 6), 12.0),
            (date(2026, 1, 8), 13.0),
            (date(2026, 1, 12), 14.0),
            (date(2026, 1, 13), 15.0),
            (date(2026, 1, 14), 16.0),
            (date(2026, 1, 15), 17.0),
            (date(2026, 1, 16), 18.0),
            (date(2026, 2, 2), 19.0),
            (date(2026, 2, 3), 20.0),
        )
    ]
    BarRepository(factory).upsert(record.id, bars)
    return record.id


def make_client(
    factory: SessionFactory,
    *,
    settings: Settings | None = None,
) -> tuple[TestClient, int]:
    instrument_id = seed_database(factory)
    instruments = InstrumentRepository(factory)
    bars = BarRepository(factory)
    bar_service = BarService(bars, instruments)
    registry = IndicatorRegistry()
    registry.register(RSIIndicator)
    registry.register(ExplodingIndicator)
    registry.register(ParameterExplodingIndicator)
    app = FastAPI()
    app.state.instrument_repository = instruments
    app.state.bar_service = bar_service
    app.state.indicator_registry = registry
    app.state.indicator_service = IndicatorService(
        bar_service=bar_service,
        instruments=instruments,
        registry=registry,
        settings=settings or default_settings(),
    )
    app.include_router(instruments_router)
    app.include_router(bars_router)
    app.include_router(indicators_router)
    register_response_handlers(app)
    return TestClient(app, raise_server_exceptions=False), instrument_id


@pytest.fixture
def api(session_factory: SessionFactory) -> Iterator[tuple[TestClient, int]]:
    client, instrument_id = make_client(session_factory)
    try:
        yield client, instrument_id
    finally:
        client.close()


def assert_envelope(payload: dict[str, object], *, success: bool) -> None:
    assert set(payload) == {"success", "data", "error", "meta"}
    assert payload["success"] is success
    if success:
        assert payload["error"] is None
    else:
        assert payload["data"] is None
        assert isinstance(payload["error"], dict)


def test_instrument_search_and_universe_list_use_success_envelope(
    api: tuple[TestClient, int],
) -> None:
    client, _ = api

    response = client.get(
        f"{API_ROOT}/instruments",
        params={"query": "Alpha", "market": "us_stock", "limit": 10},
    )
    universes = client.get(f"{API_ROOT}/universes")

    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload, success=True)
    assert [item["symbol"] for item in payload["data"]] == ["AAA"]
    assert payload["data"][0]["name"] == "Alpha"
    assert payload["meta"]["count"] == 1
    assert universes.status_code == 200
    assert universes.json()["data"] == ["nasdaq100"]
    assert_envelope(universes.json(), success=True)


@pytest.mark.parametrize(
    ("timeframe", "start", "end", "expected_dates"),
    [
        ("1d", "2026-01-08", "2026-01-13", ["2026-01-08", "2026-01-12", "2026-01-13"]),
        ("1w", "2026-01-05", "2026-01-31", ["2026-01-08", "2026-01-16"]),
        ("1M", "2026-01-01", "2026-02-03", ["2026-01-16", "2026-02-03"]),
    ],
)
def test_day_week_month_bars_preserve_actual_dates(
    api: tuple[TestClient, int],
    timeframe: str,
    start: str,
    end: str,
    expected_dates: list[str],
) -> None:
    client, instrument_id = api

    response = client.get(
        f"{API_ROOT}/bars",
        params={
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": 100,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload, success=True)
    assert [item["time"] for item in payload["data"]] == expected_dates
    assert payload["meta"] == {"count": len(expected_dates), "timeframe": timeframe}
    if timeframe == "1w":
        assert payload["data"][0]["open"] == 10.5
        assert payload["data"][0]["high"] == 14.0
        assert payload["data"][0]["low"] == 10.0
        assert payload["data"][0]["close"] == 13.0
        assert payload["data"][0]["volume"] == 300.0


def test_empty_bars_and_empty_indicator_batch_remain_successful(
    api: tuple[TestClient, int],
) -> None:
    client, instrument_id = api

    bars = client.get(
        f"{API_ROOT}/bars",
        params={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "start": "2024-01-01",
            "end": "2024-01-31",
        },
    )
    computations = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "start": "2026-01-12",
            "end": "2026-01-16",
            "indicators": [],
        },
    )

    assert bars.status_code == 200
    assert bars.json()["data"] == []
    assert bars.json()["meta"]["count"] == 0
    assert computations.status_code == 200
    assert computations.json()["data"] == []
    assert_envelope(computations.json(), success=True)


def test_descriptor_list_and_batch_compute_isolate_failure_and_use_thread(
    api: tuple[TestClient, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, instrument_id = api
    calls: list[tuple[object, tuple[object, ...]]] = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func: object, *args: object) -> object:
        calls.append((func, args))
        return await real_to_thread(func, *args)  # type: ignore[arg-type]

    monkeypatch.setattr("app.api.indicators.asyncio.to_thread", spy_to_thread)

    descriptors = client.get(f"{API_ROOT}/indicators")
    response = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "start": "2026-01-12",
            "end": "2026-01-16",
            "indicators": [
                {"instance_id": "rsi-fast", "name": "rsi", "params": {"window": 2}},
                {"instance_id": "broken", "name": "explode", "params": {}},
                {"instance_id": "rsi-slow", "name": "rsi", "params": {"window": 3}},
            ],
        },
    )
    bars_after_failure = client.get(
        f"{API_ROOT}/bars",
        params={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "start": "2026-01-12",
            "end": "2026-01-16",
        },
    )

    assert descriptors.status_code == 200
    descriptor_data = descriptors.json()["data"]
    assert {item["name"] for item in descriptor_data} == {
        "rsi",
        "explode",
        "parameter-explode",
    }
    rsi = next(item for item in descriptor_data if item["name"] == "rsi")
    assert rsi["params_schema"]["properties"]["window"]["default"] == 14
    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload, success=True)
    assert [item["instance_id"] for item in payload["data"]] == [
        "rsi-fast",
        "broken",
        "rsi-slow",
    ]
    assert payload["data"][0]["error"] is None
    assert payload["data"][0]["series"][0]["id"] == "rsi-fast:rsi"
    assert payload["data"][2]["series"][0]["id"] == "rsi-slow:rsi"
    assert all(
        point["time"] >= "2026-01-12"
        for point in payload["data"][0]["series"][0]["points"]
    )
    assert payload["data"][1]["error"] == "Indicator calculation failed"
    assert payload["data"][1]["series"] == []
    assert "private database password" not in response.text
    assert len(calls) == 1
    assert bars_after_failure.status_code == 200
    assert len(bars_after_failure.json()["data"]) == 5


def test_parameter_plugin_runtime_error_preserves_api_batch_and_is_sanitized(
    api: tuple[TestClient, int],
) -> None:
    client, instrument_id = api

    response = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "start": "2026-01-12",
            "end": "2026-01-16",
            "indicators": [
                {
                    "instance_id": "broken-params",
                    "name": "parameter-explode",
                    "params": {},
                },
                {
                    "instance_id": "healthy",
                    "name": "rsi",
                    "params": {"window": 2},
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload, success=True)
    assert payload["data"][0]["error"] == "Invalid indicator parameters"
    assert payload["data"][0]["series"] == []
    assert payload["data"][1]["error"] is None
    assert payload["data"][1]["series"][0]["id"] == "healthy:rsi"
    assert payload["data"][1]["series"][0]["points"]
    assert "private parameter validator secret" not in response.text


@pytest.mark.parametrize(
    "params",
    [
        {"instrument_id": 1, "start": "not-a-date", "end": "2026-01-02"},
        {"instrument_id": 1, "start": "2026-01-03", "end": "2026-01-02"},
        {"instrument_id": 1, "timeframe": "2d"},
        {"instrument_id": 1, "unexpected": "forbidden"},
    ],
)
def test_invalid_bar_queries_have_sanitized_validation_envelopes(
    api: tuple[TestClient, int],
    params: dict[str, object],
) -> None:
    client, _ = api

    response = client.get(f"{API_ROOT}/bars", params=params)

    assert response.status_code == 422
    assert_envelope(response.json(), success=False)
    assert response.json()["error"]["code"] == "validation_error"
    assert "Traceback" not in response.text


def test_missing_instruments_and_invalid_compute_inputs_are_sanitized(
    api: tuple[TestClient, int],
) -> None:
    client, instrument_id = api

    missing_bars = client.get(f"{API_ROOT}/bars", params={"instrument_id": 999})
    missing_compute = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": 999,
            "timeframe": "1d",
            "start": "2026-01-01",
            "end": "2026-01-02",
            "indicators": [],
        },
    )
    extra = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "start": "2026-01-01",
            "end": "2026-01-02",
            "indicators": [],
            "unexpected": True,
        },
    )

    assert missing_bars.status_code == 404
    assert missing_bars.json()["error"] == {
        "code": "instrument_not_found",
        "message": "Instrument not found",
    }
    assert missing_compute.status_code == 404
    assert extra.status_code == 422
    assert_envelope(extra.json(), success=False)
    assert "Traceback" not in extra.text


def test_duplicate_instances_and_configured_active_limit_are_rejected(
    api: tuple[TestClient, int],
) -> None:
    client, instrument_id = api
    base = {
        "instrument_id": instrument_id,
        "timeframe": "1d",
        "start": "2026-01-01",
        "end": "2026-01-16",
    }
    duplicate = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            **base,
            "indicators": [
                {"instance_id": "same", "name": "rsi", "params": {}},
                {"instance_id": "same", "name": "rsi", "params": {}},
            ],
        },
    )
    too_many = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            **base,
            "indicators": [
                {"instance_id": f"rsi-{index}", "name": "rsi", "params": {}}
                for index in range(21)
            ],
        },
    )

    assert duplicate.status_code == 422
    assert_envelope(duplicate.json(), success=False)
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "indicator_limit_exceeded"
    assert "maximum is 20" in too_many.json()["error"]["message"]
    assert_envelope(too_many.json(), success=False)


def test_compute_without_range_uses_full_history_and_slices_from_cache(
    api: tuple[TestClient, int],
) -> None:
    client, instrument_id = api

    first = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "indicators": [
                {"instance_id": "rsi-open", "name": "rsi", "params": {"window": 2}}
            ],
        },
    )
    assert first.status_code == 200
    points = first.json()["data"][0]["series"][0]["points"]
    # Seeded history has 10 bars; RSI window=2 warms up on the first two.
    assert len(points) == 8
    assert points[0]["time"] == "2026-01-08"

    paged = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "end": "2026-01-16",
            "limit": 3,
            "indicators": [
                {"instance_id": "rsi-open", "name": "rsi", "params": {"window": 2}}
            ],
        },
    )
    assert paged.status_code == 200
    paged_points = paged.json()["data"][0]["series"][0]["points"]
    times = [point["time"] for point in paged_points]
    # The last 3 bars through 2026-01-16 are 14, 15, 16; RSI emits values
    # for every one of them because warmup happened on the full history.
    assert times == ["2026-01-14", "2026-01-15", "2026-01-16"]


def test_compute_rejects_inconsistent_range_and_bad_limit(
    api: tuple[TestClient, int],
) -> None:
    client, instrument_id = api

    inconsistent = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "start": "2026-02-03",
            "end": "2026-01-05",
            "indicators": [],
        },
    )
    assert inconsistent.status_code == 422

    negative_limit = client.post(
        f"{API_ROOT}/indicators/compute",
        json={
            "instrument_id": instrument_id,
            "timeframe": "1d",
            "limit": 0,
            "indicators": [],
        },
    )
    assert negative_limit.status_code == 422
