"""Portable provenance for adapter inputs, without embedding local directory paths."""
from __future__ import annotations

import hashlib
from pathlib import Path


def fingerprint(path: str | Path) -> dict:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'filename': path.name, 'sha256': digest.hexdigest(), 'size_bytes': path.stat().st_size}
