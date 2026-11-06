"""Optional production static mount for the built frontend bundle."""

import errno
import sys
from pathlib import Path

import pytest
from app.config.application import AppSettings
from app.main import create_app
from fastapi.testclient import TestClient

TRUSTED_HOSTS = AppSettings().allowed_hosts + ("testserver",)


def build_settings(
    tmp_path: Path,
    frontend_dist: Path | None,
    *,
    serve_frontend: bool = True,
) -> AppSettings:
    return AppSettings(
        config_path=tmp_path / "settings.json",
        database_path=tmp_path / "mount.sqlite3",
        allowed_hosts=TRUSTED_HOSTS,
        read_rate_limit=1_000,
        write_rate_limit=1_000,
        compute_rate_limit=1_000,
        frontend_dist=frontend_dist,
        serve_frontend=serve_frontend,
    )


def build_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", "utf-8")
    (assets / "app.js").write_text("console.log('app')", "utf-8")
    return dist


def test_missing_bundle_keeps_api_only_behavior(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path, None, serve_frontend=False))

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/v1/unknown").status_code == 404
        assert client.get("/analysis").status_code == 404


def test_absent_directory_behaves_like_no_bundle(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path, tmp_path / "does-not-exist"))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/analysis").status_code == 404


def test_bundle_serves_spa_routes_and_assets(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    app = create_app(build_settings(tmp_path, dist))

    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "<title>app</title>" in root.text

        deep_link = client.get("/tasks")
        assert deep_link.status_code == 200
        assert "<title>app</title>" in deep_link.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "console.log" in asset.text


def test_api_404_stays_json_when_a_bundle_is_mounted(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    app = create_app(build_settings(tmp_path, dist))

    with TestClient(app) as client:
        response = client.get("/api/v1/unknown")

        assert response.status_code == 404
        payload = response.json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "http_error"
        assert "<title>app</title>" not in response.text


def test_api_prefix_without_route_is_not_rewritten_to_index(
    tmp_path: Path,
) -> None:
    dist = build_dist(tmp_path)
    app = create_app(build_settings(tmp_path, dist))

    with TestClient(app) as client:
        assert client.get("/api").status_code == 404
        assert client.get("/api/v2/whatever").status_code == 404


def test_only_assets_are_mounted_and_spa_fallback_is_state_driven(
    tmp_path: Path,
) -> None:
    dist = build_dist(tmp_path)
    app = create_app(build_settings(tmp_path, dist))

    mount_names = [
        getattr(route, "name", None)
        for route in app.routes
        if getattr(route, "name", None) == "assets"
    ]
    assert mount_names == ["assets"]
    assert app.state.frontend_index == dist / "index.html"


def test_directory_resolution_prefers_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = build_dist(tmp_path / "override")
    monkeypatch.setenv("STOCK_LAB_FRONTEND_DIST", str(override))

    assert AppSettings().resolved_frontend_dist() == override


def test_missing_override_path_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_LAB_FRONTEND_DIST", str(tmp_path / "nope"))

    assert AppSettings().resolved_frontend_dist() is None


def test_repository_relative_default_is_not_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default = AppSettings().default_frontend_dist()
    monkeypatch.chdir(tmp_path)

    assert AppSettings().resolved_frontend_dist() == (
        default if default is not None else None
    )
    assert default is None or default == Path(
        "/Users/xuyang/workspace/tv-strategy/frontend/dist"
    )


def test_bundle_without_index_is_not_served(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    app = create_app(build_settings(tmp_path, dist))

    with TestClient(app) as client:
        assert client.get("/analysis").status_code == 404
    assert app.state.frontend_index is None


def test_missing_hashed_asset_is_not_answered_with_index_html(
    tmp_path: Path,
) -> None:
    dist = build_dist(tmp_path)
    app = create_app(build_settings(tmp_path, dist))

    with TestClient(app) as client:
        stale = client.get("/assets/index-deadbeef.js")

        assert stale.status_code == 404
        assert "text/html" not in stale.headers.get("content-type", "")
        assert "<title>app</title>" not in stale.text


def test_post_to_a_client_route_is_not_rewritten(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    app = create_app(build_settings(tmp_path, dist))

    with TestClient(app) as client:
        response = client.post("/analysis", json={})

        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


def test_unmounted_app_has_no_spa_state(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path, None, serve_frontend=False))

    assert app.state.frontend_index is None


def test_symbolic_link_to_missing_bundle_is_ignored(tmp_path: Path) -> None:
    link = tmp_path / "dist-link"
    try:
        link.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError) as error:  # pragma: no cover
        if getattr(error, "errno", None) == errno.EPERM or sys.platform == "win32":
            pytest.skip("Symbolic links are unavailable on this platform")
        raise

    assert AppSettings().resolved_frontend_dist(link) is None
