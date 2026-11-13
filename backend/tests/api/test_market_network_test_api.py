"""HTTP contracts for saved-configuration market network tests."""

from datetime import date
from pathlib import Path

import pytest

from app.domain.dto import Market
from app.main import AppSettings, create_app
from app.services.market_network_test import (
    MarketNetworkTestService,
    NetworkTestResult,
)
from fastapi.testclient import TestClient

API_ROOT = "/api/v1"


def application_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        config_path=tmp_path / "settings.json",
        database_path=tmp_path / "network-test.sqlite3",
        allowed_hosts=AppSettings().allowed_hosts + ("testserver",),
        read_rate_limit=1_000,
        write_rate_limit=1_000,
        compute_rate_limit=1_000,
        serve_frontend=False,
    )


def successful_result(market: Market = "crypto") -> NetworkTestResult:
    provider = "binance" if market == "crypto" else "yfinance"
    symbol = "BINANCE:BTC/USDT" if market == "crypto" else "AAPL"
    return NetworkTestResult(
        market=market,
        provider=provider,
        symbol=symbol,
        connected=True,
        latency_ms=12.3,
        price=74015.19,
        price_date=date(2026, 11, 11),
        currency="USDT" if market == "crypto" else "USD",
    )


def test_network_test_returns_result_without_config_or_task_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def fake_test(
        self: MarketNetworkTestService,
        market: Market,
        symbol: str,
    ) -> NetworkTestResult:
        observed.update({"market": market, "symbol": symbol})
        return successful_result(market)

    monkeypatch.setattr(MarketNetworkTestService, "test", fake_test)
    app = create_app(application_settings(tmp_path))

    with TestClient(app) as client:
        before = app.state.container.config_service.get().revision
        response = client.post(
            f"{API_ROOT}/settings/markets/crypto/network-test",
            json={"symbol": "  BTC/USDT  "},
        )

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"success", "data", "error", "meta"}
        assert payload["success"] is True
        assert payload["error"] is None
        assert payload["data"] == {
            "market": "crypto",
            "provider": "binance",
            "symbol": "BINANCE:BTC/USDT",
            "connected": True,
            "latency_ms": 12.3,
            "price": 74015.19,
            "price_date": "2026-11-11",
            "currency": "USDT",
            "error_type": None,
            "detail": None,
        }
        assert observed == {"market": "crypto", "symbol": "BTC/USDT"}
        assert app.state.container.config_service.get().revision == before
        assert app.state.container.task_run_repository.list_runs() == []


def test_expected_probe_failure_uses_success_envelope_with_connected_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_test(
        self: MarketNetworkTestService,
        market: Market,
        symbol: str,
    ) -> NetworkTestResult:
        return NetworkTestResult(
            market=market,
            provider="akshare",
            symbol=symbol,
            connected=False,
            latency_ms=1.0,
            error_type="ProviderBusy",
            detail="Data source is currently in use, retry later",
        )

    monkeypatch.setattr(MarketNetworkTestService, "test", fake_test)
    app = create_app(application_settings(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            f"{API_ROOT}/settings/markets/a_share/network-test",
            json={"symbol": "600519.SH"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["connected"] is False
    assert response.json()["data"]["error_type"] == "ProviderBusy"


def test_invalid_symbols_and_markets_have_distinct_validation_contracts(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app) as client:
        invalid_symbol = client.post(
            f"{API_ROOT}/settings/markets/a_share/network-test",
            json={"symbol": "bad symbol"},
        )
        invalid_market = client.post(
            f"{API_ROOT}/settings/markets/forex/network-test",
            json={"symbol": "AAPL"},
        )
        blank_symbol = client.post(
            f"{API_ROOT}/settings/markets/us_stock/network-test",
            json={"symbol": ""},
        )

    assert invalid_symbol.status_code == 422
    assert invalid_symbol.json()["error"]["code"] == "invalid_network_test_symbol"
    assert invalid_market.status_code == 422
    assert invalid_market.json()["error"]["code"] == "validation_error"
    assert blank_symbol.status_code == 422
    assert blank_symbol.json()["error"]["code"] == "validation_error"


def test_unexpected_route_failure_does_not_leak_exception_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(
        self: MarketNetworkTestService,
        market: Market,
        symbol: str,
    ) -> NetworkTestResult:
        raise RuntimeError("private proxy credential and traceback")

    monkeypatch.setattr(MarketNetworkTestService, "test", explode)
    app = create_app(application_settings(tmp_path))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"{API_ROOT}/settings/markets/us_stock/network-test",
            json={"symbol": "AAPL"},
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private proxy credential" not in response.text
    assert "Traceback" not in response.text
