"""Synchronous provider interfaces, registry selection, and bar validation."""

import inspect
from datetime import date
from typing import get_type_hints

import pytest

from app.config.defaults import default_settings
from app.domain.dto import (
    Adjustment,
    BarDTO,
    InstrumentDTO,
    InstrumentRecord,
    UniverseSnapshot,
)
from app.providers.base import OhlcvProvider, UniverseProvider
from app.providers.errors import (
    NoDataAvailable,
    ProviderCompatibilityError,
    ProviderDataInvalid,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
    UnknownMarketError,
    UnknownProviderError,
)
from app.providers.registry import ProviderRegistry
from app.providers.validation import validate_bars


class FixtureOhlcvProvider:
    def fetch_daily(
        self,
        instrument: InstrumentDTO,
        start: date | None,
        end: date,
        adjustment: Adjustment,
    ) -> list[BarDTO]:
        return []


class FixtureUniverseProvider:
    def fetch_universe(self, universe_code: str) -> UniverseSnapshot:
        return UniverseSnapshot(
            universe_code=universe_code,
            source="fixture",
            effective_date=None,
            members=(),
        )


def instrument_record() -> InstrumentRecord:
    return InstrumentRecord(
        id=1,
        active=True,
        symbol="AAA",
        name="Alpha",
        market="us_stock",
        exchange="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        instrument_type="stock",
        provider_symbol="AAA",
    )


def bar(day: date = date(2026, 1, 1), **changes: object) -> BarDTO:
    values: dict[str, object] = {
        "time": day,
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 100.0,
        "source": "fixture",
        "adjustment": "qfq",
    }
    values.update(changes)
    return BarDTO(**values)  # type: ignore[arg-type]


def test_provider_methods_have_exact_synchronous_interfaces() -> None:
    ohlcv_signature = inspect.signature(OhlcvProvider.fetch_daily)
    assert list(ohlcv_signature.parameters) == [
        "self",
        "instrument",
        "start",
        "end",
        "adjustment",
    ]
    assert not inspect.iscoroutinefunction(OhlcvProvider.fetch_daily)
    ohlcv_hints = get_type_hints(OhlcvProvider.fetch_daily)
    assert ohlcv_hints["instrument"] is InstrumentDTO
    assert ohlcv_hints["start"] == date | None
    assert ohlcv_hints["end"] is date
    assert ohlcv_hints["adjustment"] == Adjustment
    assert ohlcv_hints["return"] == list[BarDTO]

    universe_signature = inspect.signature(UniverseProvider.fetch_universe)
    assert list(universe_signature.parameters) == ["self", "universe_code"]
    assert not inspect.iscoroutinefunction(UniverseProvider.fetch_universe)
    universe_hints = get_type_hints(UniverseProvider.fetch_universe)
    assert universe_hints["universe_code"] is str
    assert universe_hints["return"] is UniverseSnapshot


def test_instrument_record_is_accepted_through_the_instrument_dto_contract() -> None:
    provider = FixtureOhlcvProvider()

    assert provider.fetch_daily(
        instrument_record(), None, date(2026, 1, 31), "qfq"
    ) == []


def test_provider_error_taxonomy_has_safe_default_messages() -> None:
    for error_type in (
        ProviderUnavailable,
        ProviderRateLimited,
        ProviderDataInvalid,
        NoDataAvailable,
    ):
        error = error_type()
        assert isinstance(error, ProviderError)
        assert str(error)
        assert "http" not in str(error).lower()


def build_registry(
    ohlcv_providers: dict[str, FixtureOhlcvProvider] | None = None,
    universe_providers: dict[str, FixtureUniverseProvider] | None = None,
) -> ProviderRegistry:
    return ProviderRegistry(
        settings=default_settings(),
        ohlcv_providers=ohlcv_providers or {},
        universe_providers=universe_providers or {},
    )


def test_registry_uses_configured_default_and_explicit_compatible_provider() -> None:
    akshare = FixtureOhlcvProvider()
    yfinance = FixtureOhlcvProvider()
    registry = build_registry({"akshare": akshare, "yfinance": yfinance})

    assert registry.get_ohlcv("a_share", None) is akshare
    assert registry.get_ohlcv("a_share", "akshare") is akshare
    assert registry.get_ohlcv("us_stock", None) is yfinance


def test_registry_rejects_unknown_provider_and_unknown_market() -> None:
    registry = build_registry()

    with pytest.raises(UnknownProviderError):
        registry.get_ohlcv("a_share", "not-a-provider")
    with pytest.raises(UnknownMarketError):
        registry.get_ohlcv("not-a-market", None)


def test_registry_rejects_known_but_incompatible_market_provider_pair() -> None:
    registry = build_registry({"yfinance": FixtureOhlcvProvider()})

    with pytest.raises(ProviderCompatibilityError):
        registry.get_ohlcv("a_share", "yfinance")


def test_registry_reports_compatible_but_unregistered_provider_unavailable() -> None:
    registry = build_registry()

    with pytest.raises(ProviderUnavailable):
        registry.get_ohlcv("a_share", "baostock")


def test_registry_detaches_provider_mappings_and_resolves_universes() -> None:
    akshare = FixtureOhlcvProvider()
    replacement = FixtureOhlcvProvider()
    universe = FixtureUniverseProvider()
    ohlcv_providers = {"akshare": akshare}
    registry = build_registry(ohlcv_providers, {"csi300": universe})
    ohlcv_providers["akshare"] = replacement

    assert registry.get_ohlcv("a_share", None) is akshare
    assert registry.get_universe("csi300") is universe
    with pytest.raises(UnknownProviderError):
        registry.get_universe("unknown-universe")


def test_validate_bars_returns_a_new_sorted_list_without_mutating_input() -> None:
    earliest = bar(date(2026, 1, 1))
    latest = bar(date(2026, 1, 3))
    middle = bar(date(2026, 1, 2))
    rows = [latest, earliest, middle]
    original_order = tuple(rows)

    validated = validate_bars(rows)

    assert validated == [earliest, middle, latest]
    assert validated is not rows
    assert tuple(rows) == original_order
    expected_order = [earliest, middle, latest]
    assert all(
        item is expected
        for item, expected in zip(validated, expected_order, strict=True)
    )


def test_validate_bars_accepts_iterators_empty_data_and_missing_volume() -> None:
    row = bar(volume=None)

    assert validate_bars(iter([row])) == [row]
    assert validate_bars([]) == []


def test_validate_bars_rejects_duplicate_dates() -> None:
    with pytest.raises(ProviderDataInvalid, match="Duplicate bar date"):
        validate_bars([bar(), bar()])


@pytest.mark.parametrize(
    "changes",
    [
        {"high": 8.0},
        {"open": 13.0},
        {"open": 8.0},
        {"close": 13.0},
        {"close": 8.0},
    ],
    ids=[
        "high-below-low",
        "open-above-high",
        "open-below-low",
        "close-above-high",
        "close-below-low",
    ],
)
def test_validate_bars_rejects_invalid_ohlc_relationships(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ProviderDataInvalid, match="OHLC"):
        validate_bars([bar(**changes)])


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_validate_bars_rejects_every_non_finite_numeric_field(
    field: str,
    bad_value: float,
) -> None:
    with pytest.raises(ProviderDataInvalid, match="finite"):
        validate_bars([bar(**{field: bad_value})])


@pytest.mark.parametrize("volume", [-0.01, -1, float("-inf")])
def test_validate_bars_rejects_negative_volume(volume: float) -> None:
    with pytest.raises(ProviderDataInvalid):
        validate_bars([bar(volume=volume)])


@pytest.mark.parametrize(
    "row",
    [
        object(),
        bar(open=True),
        bar(volume=False),
        bar(open="10"),
        bar(time="2026-01-01"),
        bar(source=" "),
        bar(adjustment="invalid"),
    ],
    ids=[
        "wrong-row",
        "boolean-price",
        "boolean-volume",
        "string-price",
        "string-date",
        "blank-source",
        "unknown-adjustment",
    ],
)
def test_validate_bars_rejects_malformed_dto_values_visibly(row: object) -> None:
    with pytest.raises(ProviderDataInvalid):
        validate_bars([row])  # type: ignore[list-item]
