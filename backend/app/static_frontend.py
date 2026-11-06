"""Serve a built frontend bundle without shadowing API or late-added routes."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

ASSET_MOUNT_PATH = "/assets"
ASSET_MOUNT_NAME = "assets"
INDEX_FILE = "index.html"
FRONTEND_STATE_ATTRIBUTE = "frontend_index"
SPA_METHODS = frozenset({"GET", "HEAD"})
# Prefixes that must never be answered with index.html: a stale hashed asset or
# an API call served an HTML body breaks the client in confusing ways.
NON_SPA_PREFIXES = ("api", "assets")


def configure_frontend(application: FastAPI, dist: Path | None) -> bool:
    """Mount hashed assets and remember the SPA entry point for 404 fallback.

    The SPA fallback is served from the 404 handler rather than a catch-all
    mount at ``/`` so that routes registered after app creation (plugins,
    tests, future routers) are matched normally.
    """
    setattr(application.state, FRONTEND_STATE_ATTRIBUTE, None)
    if dist is None:
        return False
    index = dist / INDEX_FILE
    if not index.is_file():
        logger.warning(
            "Frontend bundle at %s has no %s; skipping static serving",
            dist,
            INDEX_FILE,
        )
        return False

    assets = dist / "assets"
    if assets.is_dir():
        application.mount(
            ASSET_MOUNT_PATH,
            StaticFiles(directory=assets),
            name=ASSET_MOUNT_NAME,
        )
    setattr(application.state, FRONTEND_STATE_ATTRIBUTE, index)
    return True


def frontend_index(request) -> FileResponse | None:  # type: ignore[no-untyped-def]
    """Return the SPA entry point for a client-side route, or None."""
    if request.method not in SPA_METHODS:
        return None
    relative = request.url.path.lstrip("/")
    if relative.split("/", 1)[0] in NON_SPA_PREFIXES:
        return None
    index = getattr(request.app.state, FRONTEND_STATE_ATTRIBUTE, None)
    if not isinstance(index, Path) or not index.is_file():
        return None
    return FileResponse(index, media_type="text/html")
