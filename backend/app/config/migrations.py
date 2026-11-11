"""Backward-compatible migration for the data-source settings split."""

from copy import deepcopy

from app.config.models import CryptoSymbol
from pydantic import TypeAdapter

DAILY_TASK_BY_MARKET = {
    "a_share": "market.sync_a_daily",
    "hk_stock": "market.sync_hk_daily",
    "us_stock": "market.sync_us_daily",
    "crypto": "market.sync_crypto_daily",
}
MIGRATED_FIELDS = ("history_years", "overlap_days", "concurrency")
RETIRED_FIELDS = (*MIGRATED_FIELDS, "max_retries", "symbols")
CRYPTO_SYMBOL_LIST = TypeAdapter(list[CryptoSymbol])


def migrate_legacy_settings_document(document: dict) -> dict:
    """Move legacy sync parameters into Tasks without mutating the input."""
    if not isinstance(document, dict):
        return document
    migrated = deepcopy(document)
    markets = migrated.get("markets")
    if not isinstance(markets, dict):
        return migrated
    if "tasks" not in migrated:
        migrated["tasks"] = {}
    tasks = migrated["tasks"]

    for market, task_name in DAILY_TASK_BY_MARKET.items():
        market_document = markets.get(market)
        if not isinstance(market_document, dict):
            continue
        if isinstance(tasks, dict):
            _migrate_market_params(market_document, tasks, task_name)
            if market == "crypto":
                _migrate_crypto_pairs(market_document, tasks, task_name)
        for field in RETIRED_FIELDS:
            market_document.pop(field, None)
    return migrated


def _migrate_crypto_pairs(
    market_document: dict,
    tasks: dict,
    task_name: str,
) -> None:
    if "symbols" not in market_document:
        return
    pairs = CRYPTO_SYMBOL_LIST.validate_python(market_document["symbols"])
    task_document = tasks.get(task_name, {})
    if not isinstance(task_document, dict):
        return
    current_params = task_document.get("params", {})
    if not isinstance(current_params, dict) or "spot_pairs" in current_params:
        return
    tasks[task_name] = {
        **task_document,
        "params": {
            **current_params,
            "spot_pairs": [pair.model_dump(mode="python") for pair in pairs],
        },
    }


def _migrate_market_params(
    market_document: dict,
    tasks: dict,
    task_name: str,
) -> None:
    task_document = tasks.get(task_name, {})
    if not isinstance(task_document, dict):
        return
    current_params = task_document.get("params", {})
    if not isinstance(current_params, dict):
        return
    params = dict(current_params)
    for field in MIGRATED_FIELDS:
        if field in market_document and field not in params:
            params[field] = market_document[field]
    if params != current_params:
        tasks[task_name] = {**task_document, "params": params}
