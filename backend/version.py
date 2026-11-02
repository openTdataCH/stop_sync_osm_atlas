"""Canonical review-application release version and engine pin."""

from pathlib import Path

APP_VERSION = "0.6.0"

ENGINE_REPOSITORY_URL = "https://github.com/openTdataCH/osm-public-transport-matcher"


def engine_blob_base() -> str:
    """Public URL prefix of engine files at the commit pinned in engine.ref."""
    ref = (Path(__file__).resolve().parents[1] / "engine.ref").read_text().strip()
    return f"{ENGINE_REPOSITORY_URL}/blob/{ref}/"
