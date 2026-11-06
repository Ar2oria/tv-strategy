"""Loopback Host validation and browser mutation-origin boundaries."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import AppSettings, create_app

RUN_PATH = "/api/v1/tasks/system.purge_task_history/runs"
LOOPBACK_BASE_URL = "http://127.0.0.1"


def application_settings(tmp_path: Path, **overrides: object) -> AppSettings:
    values = {
        "config_path": tmp_path / "settings.json",
        "database_path": tmp_path / "request-trust.sqlite3",
        "read_rate_limit": 1_000,
        "write_rate_limit": 1_000,
        "compute_rate_limit": 1_000,
    }
    return AppSettings(**{**values, **overrides})


def assert_rejection(response: object, status: int, code: str) -> None:
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"success", "data", "error", "meta"}
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == code
    assert "Traceback" not in response.text


def test_local_trust_defaults_are_exact_and_wildcards_are_invalid() -> None:
    settings = AppSettings()

    assert settings.allowed_hosts == ("127.0.0.1", "localhost", "::1")
    assert settings.allowed_origins == (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    with pytest.raises(ValidationError):
        settings.allowed_hosts = ("other",)

    invalid_values = (
        {"allowed_hosts": ("*",)},
        {"allowed_hosts": ("*.local",)},
        {"allowed_hosts": ("http://localhost",)},
        {"allowed_origins": ("*",)},
        {"allowed_origins": ("http://*.local",)},
        {"allowed_origins": ("null",)},
        {"allowed_origins": ("http://localhost:5173/path",)},
    )
    for values in invalid_values:
        with pytest.raises(ValidationError):
            AppSettings(**values)


def test_allowed_origins_are_normalized_without_suffix_matching() -> None:
    settings = AppSettings(allowed_origins=("HTTP://LOCALHOST:80/",))

    assert settings.allowed_origins == ("http://localhost",)


def test_ipv6_loopback_host_is_accepted(tmp_path: Path) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app, base_url="http://[::1]") as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_hostile_host_cannot_execute_a_task(tmp_path: Path) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app, base_url=LOOPBACK_BASE_URL) as client:
        response = client.post(
            RUN_PATH,
            content=b"",
            headers={"Host": "evil.example", "Content-Type": "text/plain"},
        )
        history = client.get(RUN_PATH)

        assert_rejection(response, 400, "invalid_host")
        assert "evil.example" not in response.text
        assert history.status_code == 200
        assert history.json()["data"] == []


def test_cross_site_simple_post_cannot_execute_a_task(tmp_path: Path) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app, base_url=LOOPBACK_BASE_URL) as client:
        response = client.post(
            RUN_PATH,
            content=b"",
            headers={
                "Content-Type": "text/plain",
                "Origin": "http://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        history = client.get(RUN_PATH)

        assert_rejection(response, 403, "request_origin_forbidden")
        assert "evil.example" not in response.text
        assert history.status_code == 200
        assert history.json()["data"] == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "null"},
        {"Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://localhost:5173.evil.example"},
    ],
)
def test_other_hostile_mutation_metadata_is_forbidden(
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app, base_url=LOOPBACK_BASE_URL) as client:
        response = client.post(RUN_PATH, headers=headers)

        assert_rejection(response, 403, "request_origin_forbidden")
        assert client.get(RUN_PATH).json()["data"] == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "HTTP://127.0.0.1:80", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://localhost:5173"},
        {"Sec-Fetch-Site": "none"},
    ],
    ids=["headerless", "same-origin", "normalized-origin", "vite", "direct-browser"],
)
def test_allowed_task_posts_reach_the_runner(
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    app = create_app(application_settings(tmp_path))

    with TestClient(app, base_url=LOOPBACK_BASE_URL) as client:
        response = client.post(RUN_PATH, headers=headers)

        assert response.status_code == 202
        assert response.json()["success"] is True
        assert response.json()["data"]["task_name"] == "system.purge_task_history"
