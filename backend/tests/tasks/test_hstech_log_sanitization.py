"""HSTECH raw PDF text must never enter public Task serialization."""

import json
from unittest.mock import Mock

import pytest

import app.providers.hstech_universe as universe_adapter
from app.config.defaults import default_settings
from app.db.database import SessionFactory
from app.providers.errors import ProviderDataInvalid
from app.providers.hstech_parser import parse_hstech_constituents
from app.providers.registry import ProviderRegistry
from app.repositories.bars import BarRepository
from app.repositories.instruments import InstrumentRepository
from app.repositories.task_runs import TaskRunRepository
from app.services.resources import RuntimeResources
from app.tasks.base import TaskContext
from app.tasks.builtin.sync_universes import SyncUniversesTask, UniverseSyncParams
from tests.providers.test_hstech_parser import build_text_pdf

RAW_SECRET = "SECRET_TOKEN=raw-secret"
VALID_ROW = (
    "0700 Tencent Holdings Ltd Information Technology Ordinary Shares 8.25"
)


def malicious_pdf_lines() -> list[str]:
    return [
        "No. of Constituents: 1",
        "CONSTITUENTS",
        "Stock Code Company Name Industry Share Type Weighting (%)",
        *(["Weighting"] * 17),
        RAW_SECRET,
        VALID_ROW,
        "Disclaimer: fixture text only",
    ]


def test_malicious_pdf_line_uses_only_a_static_indexed_error() -> None:
    with pytest.raises(ProviderDataInvalid) as captured:
        parse_hstech_constituents(
            "\n".join(malicious_pdf_lines()),
            universe_adapter.SOURCE,
        )

    error = captured.value
    assert RAW_SECRET not in str(error)
    assert RAW_SECRET not in error.public_detail
    assert "raw-secret" not in (error.detail or "")
    assert "Invalid HSTECH constituent row at index 17" in error.public_detail


@pytest.mark.anyio
async def test_malicious_pdf_line_is_absent_from_task_result_and_persisted_logs(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
) -> None:
    monkeypatch.setattr(
        universe_adapter,
        "fetch_bytes",
        Mock(return_value=build_text_pdf(malicious_pdf_lines())),
    )
    settings = default_settings()
    registry = ProviderRegistry(
        settings=settings,
        universe_providers={"hstech": universe_adapter.HstechUniverseProvider()},
    )
    runs = TaskRunRepository(session_factory)
    run = runs.create_run("fixture.hstech-sanitization", "manual")
    context = TaskContext(
        run_id=run.id,
        settings=settings,
        resources=RuntimeResources(
            instrument_repository=InstrumentRepository(session_factory),
            bar_repository=BarRepository(session_factory),
            provider_registry=registry,
        ),
        runs=runs,
    )

    result = await SyncUniversesTask().run(
        context,
        UniverseSyncParams(universe_codes=("hstech",)),
    )

    serialized_result = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    logs = runs.list_logs(run.id)
    serialized_logs = json.dumps(
        [{"message": log.message, "context": log.context} for log in logs],
        sort_keys=True,
    )
    assert result.status == "failed"
    assert len(logs) == 1
    assert RAW_SECRET not in serialized_result
    assert RAW_SECRET not in serialized_logs
    assert "raw-secret" not in serialized_result
    assert "raw-secret" not in serialized_logs
    assert "index 17" in serialized_result
    assert "index 17" in serialized_logs
