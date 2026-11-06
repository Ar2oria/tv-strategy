"""Global rate limits, streamed body limits, and sanitized error behavior."""

from pathlib import Path

import httpx
import pytest
from app.main import AppSettings, create_app
from app.middleware.rate_limit import (
    InMemoryFixedWindowRateLimiter,
    RateBucket,
    RateLimitMiddleware,
    RateLimitPolicy,
)
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.types import Receive, Scope, Send

API_ROOT = "/api/v1"


def application_settings(tmp_path: Path, **overrides: object) -> AppSettings:
    values = {
        "config_path": tmp_path / "settings.json",
        "database_path": tmp_path / "security.sqlite3",
        "allowed_hosts": AppSettings().allowed_hosts + ("testserver",),
        "read_rate_limit": 1_000,
        "write_rate_limit": 1_000,
        "compute_rate_limit": 1_000,
        "max_request_body_bytes": 1_024,
        "serve_frontend": False,
    }
    return AppSettings(**{**values, **overrides})


def assert_api_error(response: object, status: int, code: str) -> None:
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"success", "data", "error", "meta"}
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == code
    assert "Traceback" not in response.text


def test_health_api_404_and_explicit_non_api_404_are_distinct(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app) as client:
        health = client.get("/health")
        api_missing = client.get("/api/v1/does-not-exist")
        non_api_missing = client.get("/does-not-exist")

        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert_api_error(api_missing, 404, "http_error")
        assert non_api_missing.status_code == 404
        assert non_api_missing.json() == {"detail": "Not Found"}


def test_validation_and_unexpected_api_errors_are_sanitized(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path))

    @app.get("/api/v1/test-explosion")
    def explode() -> None:
        raise RuntimeError("private token and database path")

    with TestClient(app, raise_server_exceptions=False) as client:
        invalid = client.put(f"{API_ROOT}/settings", json={"expected_revision": 0})
        unexpected = client.get("/api/v1/test-explosion")

        assert_api_error(invalid, 422, "validation_error")
        assert_api_error(unexpected, 500, "internal_error")
        assert "private token" not in unexpected.text
        assert "database path" not in unexpected.text


def test_read_limit_covers_health_and_api_routes_globally(tmp_path: Path) -> None:
    app = create_app(application_settings(tmp_path, read_rate_limit=2))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get(f"{API_ROOT}/settings").status_code == 200
        limited_health = client.get("/health")
        limited_api = client.get(f"{API_ROOT}/settings")

        assert limited_health.status_code == 429
        assert limited_health.json() == {"detail": "Too many requests"}
        assert int(limited_health.headers["Retry-After"]) >= 1
        assert_api_error(limited_api, 429, "rate_limit_exceeded")
        assert int(limited_api.headers["Retry-After"]) >= 1


def test_write_bucket_is_stricter_and_independent_from_reads(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path, write_rate_limit=1))

    with TestClient(app) as client:
        first = client.put(f"{API_ROOT}/settings", json={})
        limited = client.put(f"{API_ROOT}/settings", json={})
        read = client.get(f"{API_ROOT}/settings")

        assert_api_error(first, 422, "validation_error")
        assert_api_error(limited, 429, "rate_limit_exceeded")
        assert read.status_code == 200


def test_compute_and_immediate_execution_share_the_strict_compute_bucket(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path, compute_rate_limit=2))
    computation = {
        "instrument_id": 1,
        "timeframe": "1d",
        "start": "2026-01-01",
        "end": "2026-01-02",
        "indicators": [],
    }

    with TestClient(app) as client:
        assert (
            client.post(f"{API_ROOT}/indicators/compute", json=computation).status_code
            == 404
        )
        assert (
            client.post(f"{API_ROOT}/indicators/compute", json=computation).status_code
            == 404
        )
        limited_compute = client.post(
            f"{API_ROOT}/indicators/compute", json=computation
        )
        limited_run = client.post(
            f"{API_ROOT}/tasks/{'system.purge_task_history'}/runs"
        )
        write = client.put(f"{API_ROOT}/settings", json={})

        assert_api_error(limited_compute, 429, "rate_limit_exceeded")
        assert_api_error(limited_run, 429, "rate_limit_exceeded")
        assert_api_error(write, 422, "validation_error")


def test_fixed_window_recovers_and_isolates_clients() -> None:
    now = [10.0]
    limiter = InMemoryFixedWindowRateLimiter(
        RateLimitPolicy(read=1, write=2, compute=3, window_seconds=10),
        clock=lambda: now[0],
    )

    first = limiter.check("client-a", RateBucket.READ)
    limited = limiter.check("client-a", RateBucket.READ)
    other_client = limiter.check("client-b", RateBucket.READ)
    now[0] = 20.0
    next_window = limiter.check("client-a", RateBucket.READ)

    assert first.allowed
    assert not limited.allowed
    assert 1 <= limited.retry_after <= 10
    assert other_client.allowed
    assert next_window.allowed


def test_rate_limit_capacity_configuration_is_validated(tmp_path: Path) -> None:
    assert AppSettings().rate_limit_max_entries == 4_096
    assert (
        application_settings(tmp_path, rate_limit_max_entries=2).rate_limit_max_entries
        == 2
    )
    with pytest.raises(ValidationError):
        application_settings(tmp_path, rate_limit_max_entries=0)


@pytest.mark.anyio
async def test_new_clients_fail_closed_at_capacity_without_evicting_existing() -> None:
    now = [10.0]

    async def healthy(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"status": "ok"})
        await response(scope, receive, send)

    middleware = RateLimitMiddleware(
        healthy,
        policy=RateLimitPolicy(
            read=100,
            write=100,
            compute=100,
            window_seconds=10,
            max_entries=2,
        ),
        clock=lambda: now[0],
    )

    async def request(client_id: str) -> httpx.Response:
        transport = httpx.ASGITransport(
            app=middleware,
            client=(client_id, 123),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(f"{API_ROOT}/settings")

    assert (await request("client-a")).status_code == 200
    assert (await request("client-b")).status_code == 200

    overflow = await request("client-c")
    another_overflow = await request("client-d")

    assert (
        overflow.status_code,
        another_overflow.status_code,
        len(middleware.limiter._counters),
    ) == (429, 429, 2)
    assert_api_error(overflow, 429, "rate_limit_exceeded")
    assert_api_error(another_overflow, 429, "rate_limit_exceeded")
    assert 1 <= int(overflow.headers["Retry-After"]) <= 10
    assert len(middleware.limiter._counters) == 2
    assert set(middleware.limiter._counters) == {
        ("client-a", RateBucket.READ),
        ("client-b", RateBucket.READ),
    }

    assert (await request("client-a")).status_code == 200
    assert len(middleware.limiter._counters) == 2

    now[0] = 20.0
    admitted_next_window = await request("client-c")

    assert admitted_next_window.status_code == 200
    assert set(middleware.limiter._counters) == {("client-c", RateBucket.READ)}


def test_body_limit_counts_actual_bytes_not_spoofed_content_length(
    tmp_path: Path,
) -> None:
    app = create_app(application_settings(tmp_path, max_request_body_bytes=32))

    with TestClient(app) as client:
        at_limit = client.put(
            f"{API_ROOT}/settings",
            content=b"x" * 32,
            headers={"Content-Type": "application/json"},
        )
        spoofed = client.put(
            f"{API_ROOT}/settings",
            content=b"x" * 33,
            headers={"Content-Type": "application/json", "Content-Length": "1"},
        )

        assert_api_error(at_limit, 422, "validation_error")
        assert_api_error(spoofed, 413, "request_too_large")
        assert app.state.container.config_service.get().revision == 0


def test_streamed_chunked_and_non_api_bodies_are_bounded(tmp_path: Path) -> None:
    app = create_app(application_settings(tmp_path, max_request_body_bytes=16))

    with TestClient(app) as client:
        chunked = client.put(
            f"{API_ROOT}/settings",
            content=iter(
                [b'{"expected_revision":0,', b'"padding":"' + b"x" * 40 + b'"}']
            ),
            headers={"Content-Type": "application/json"},
        )
        non_api = client.post("/not-an-api-route", content=b"x" * 17)

        assert_api_error(chunked, 413, "request_too_large")
        assert non_api.status_code == 413
        assert non_api.json() == {"detail": "Request is too large"}
