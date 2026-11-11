"""Canonical review-application release version, engine pin and engine checkout."""

import os
from pathlib import Path
import re

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


def app_revision() -> str | None:
    """The commit this code runs at: ``APP_REVISION``, else a ``REVISION`` file beside the code, else the checkout's
    ``.git``, read as files. None when none of them names a commit, as in an image built without them."""
    def read(path):
        try:
            return path.read_text().strip()
        except OSError:
            return ''

    revision = os.getenv('APP_REVISION', '').strip() or read(APP_ROOT / 'REVISION')
    if not revision:
        git = APP_ROOT / '.git'
        if git.is_file():
            # A linked worktree: its HEAD is in its own folder, the branches in the shared one.
            git = (APP_ROOT / read(git).removeprefix('gitdir:').strip()).resolve()
        shared = (git / (read(git / 'commondir') or '.')).resolve()
        revision = read(git / 'HEAD')
        if revision.startswith('ref:'):
            ref = revision[4:].strip()
            revision = read(shared / ref) or next(
                (line.split()[0] for line in read(shared / 'packed-refs').splitlines() if line.endswith(' ' + ref)), '')
    return revision.lower() if re.fullmatch(r'[0-9a-fA-F]{40}', revision) else None
