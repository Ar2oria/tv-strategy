"""Production-container provider hot-switch and full-replacement contracts."""

from datetime import date
from pathlib import Path

import pytest

from app.bootstrap import build_container
from app.config.application import AppSettings
from app.config.models import Settings
from app.domain.dto import InstrumentDTO
from app.providers.akshare_ohlcv import AkshareOhlcvProvider
from app.providers.baostock_ohlcv import BaoStockOhlcvProvider
from app.providers.yahoo_ohlcv import YahooOhlcvProvider
from app.tasks.base import TaskContext
from app.tasks.builtin.sync_daily import (
    AShareDailySyncTask,
    DailySyncParams,
    HKStockDailySyncTask,
)
from tests.market_sync_fixtures import bar


def instrument(market: str) -> InstrumentDTO:
    if market == "hk_stock":
        return InstrumentDTO(
            symbol="0700.HK",
            name="Tencent",
            market="hk_stock",
            exchange="HKEX",
            currency="HKD",
            timezone="Asia/Hong_Kong",
            instrument_type="stock",
            provider_symbol="0700.HK",
        )
    return InstrumentDTO(
        symbol="600000.SH",
        name="Pudong Development Bank",
        market="a_share",
        exchange="SSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        instrument_type="stock",
        provider_symbol="600000",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("market", "target", "target_type", "task_type"),
    [
        ("hk_stock", "yfinance", YahooOhlcvProvider, HKStockDailySyncTask),
        ("a_share", "baostock", BaoStockOhlcvProvider, AShareDailySyncTask),
    ],
)
async def test_hot_switch_uses_new_provider_and_source_for_mocked_full_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    market: str,
    target: str,
    target_type: type,
    task_type: type,
) -> None:
    container = build_container(
        AppSettings(
            config_path=tmp_path / f"{market}-settings.json",
            database_path=tmp_path / f"{market}-hot.sqlite3",
        )
    )
    try:
        dto = instrument(market)
        record = container.instrument_repository.upsert_catalog(dto)[0]
        original = bar(date.today(), source="akshare", adjustment="qfq")
        container.bar_repository.upsert(record.id, original)
        original_resources = container.resources
        original_provider = original_resources.provider_registry.get_ohlcv(market)  # type: ignore[union-attr]
        assert isinstance(original_provider, AkshareOhlcvProvider)

        current = container.config_service.get()
        changed = current.markets[market].model_copy(
            update={"provider": target, "request_timeout_seconds": 7.25}
        )
        candidate = Settings.model_validate(
            current.model_copy(
                update={"markets": {**current.markets, market: changed}}
            ).model_dump(mode="python")
        )
        container.apply_provider_settings(candidate)
        replacement_resources = container.resources
        replacement_provider = replacement_resources.provider_registry.get_ohlcv(market)  # type: ignore[union-attr]
        assert isinstance(replacement_provider, target_type)
        assert replacement_provider.request_timeout_seconds == 7.25
        assert original_provider.request_timeout_seconds == 20.0
        assert original_resources.provider_registry.get_ohlcv(market) is original_provider  # type: ignore[union-attr]
        assert container.task_runner.resources is replacement_resources

        calls = []

        def fake_fetch(self: object, *args: object) -> list[object]:
            calls.append((self, args))
            return [bar(date.today(), source=target, adjustment="qfq")]

        monkeypatch.setattr(target_type, "fetch_daily", fake_fetch)
        run = container.task_run_repository.create_run("fixture.hot-switch", "manual")
        context = TaskContext(
            run_id=run.id,
            settings=candidate,
            resources=replacement_resources,
            runs=container.task_run_repository,
        )

        result = await task_type().run(
            context,
            DailySyncParams(symbols=(dto.symbol,), full_refresh=True),
        )

        assert result.status == "success"
        assert result.details["succeeded"] == 1
        assert len(calls) == 1
        assert calls[0][0] is replacement_provider
        stored = container.bar_repository.get_all_until(record.id, date.today())
        assert len(stored) == 1
        assert stored[0].source == target
        assert stored[0].adjustment == "qfq"
    finally:
        container.session_factory.dispose()
