"""Canonical review-application release version, engine pin and engine checkout."""

import os
from pathlib import Path

APP_VERSION = "0.6.0"

ENGINE_REPOSITORY_URL = "https://github.com/openTdataCH/osm-public-transport-matcher"

APP_ROOT = Path(__file__).resolve().parents[1]


def engine_blob_base() -> str:
    """Public URL prefix of engine files at the commit pinned in engine.ref."""
    ref = (APP_ROOT / "engine.ref").read_text().strip()
    return f"{ENGINE_REPOSITORY_URL}/blob/{ref}/"


def engine_dir() -> Path:
    """The engine checkout: ``ENGINE_DIR`` if set (relative to this app), else ``engine/``, else ``../engine``.

    ``engine/`` is where CI checks out the engine and where the app image keeps the
    engine's documentation; a developer usually has the sibling ``../engine``.
    """
    configured = os.getenv("ENGINE_DIR", "").strip()
    if configured:
        return (APP_ROOT / configured).resolve()
    nested = APP_ROOT / "engine"
    return (nested if (nested / "pyproject.toml").is_file() else APP_ROOT.parent / "engine").resolve()
