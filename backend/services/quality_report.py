"""The evidence the code quality dashboard shows: a local run, or the CI run of the commit this code runs at."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from backend.services import ci_release
from backend.version import app_revision

# Written by `make quality` or `python scripts/quality.py map` in a checkout; Git ignores it.
LOCAL = 'quality/evidence.json'
CACHE = '.cache/quality'
MAX_BYTES = 32 * 1024 * 1024
# After GitHub had nothing for a commit, ask again only this many seconds later, not on every page view.
RETRY_SECONDS = 300
_loaded: dict[str, dict] = {}
_missed: dict[str, float] = {}


class EvidenceUnavailable(Exception):
    """Nothing to show. ``reason`` is ``unknown_commit`` or ``no_results``; ``revision`` the commit asked for."""

    def __init__(self, reason, revision=None):
        super().__init__(reason)
        self.reason, self.revision = reason, revision


def _validated(evidence):
    """The evidence when it has the shape the dashboard reads; ValueError otherwise, so half a file is never drawn."""
    if not isinstance(evidence, dict) or evidence.get('schema_version') != 1:
        raise ValueError('unsupported evidence')
    code_map, report = evidence.get('code_map'), evidence.get('report')
    if not isinstance(code_map, dict) or code_map.get('schema_version') != 1 or any(not isinstance(code_map.get(key), list) for key in ('modules', 'files', 'links')):
        raise ValueError('unsupported code map')
    if report is not None:
        if not isinstance(report, dict) or not isinstance(report.get('revision'), dict) or not isinstance(report.get('modules'), dict):
            raise ValueError('unsupported report')
        if any(not isinstance(row, dict) for row in report['modules'].values()) or any(not isinstance(check, dict) for check in report.get('checks', [])):
            raise ValueError('unsupported report')
    return evidence


def download(revision):
    """What CI published for ``revision``, as bytes; None when there is nothing yet or GitHub cannot be reached."""
    return ci_release.download(f'quality-{revision}.json', MAX_BYTES)


def load_evidence(root):
    """``(evidence, source, revision)`` for the dashboard, or EvidenceUnavailable.

    A local run's file wins and is ``local``. Otherwise the evidence is the ``ci`` run of this code's commit:
    downloaded once, kept in ``.cache`` and in memory, because the file of a commit never changes.
    """
    root = Path(root)
    revision = app_revision()
    try:
        return _validated(json.loads((root / LOCAL).read_text())), 'local', revision
    except (OSError, ValueError):
        pass
    if revision is None:
        raise EvidenceUnavailable('unknown_commit')
    if revision in _loaded:
        return _loaded[revision], 'ci', revision
    cached = root / CACHE / f'{revision}.json'
    try:
        evidence = _validated(json.loads(cached.read_text()))
    except (OSError, ValueError):
        if time.monotonic() - _missed.get(revision, -RETRY_SECONDS) < RETRY_SECONDS:
            raise EvidenceUnavailable('no_results', revision)
        body = download(revision)
        try:
            evidence = _validated(json.loads(body)) if body else None
        except ValueError:
            evidence = None
        if evidence is None:
            _missed[revision] = time.monotonic()
            raise EvidenceUnavailable('no_results', revision)
        try:
            # Written beside the final name and renamed, so another worker never reads half a file.
            cached.parent.mkdir(parents=True, exist_ok=True)
            temporary = cached.with_name(f'{cached.name}.{os.getpid()}.tmp')
            temporary.write_bytes(body)
            temporary.replace(cached)
        except OSError:
            pass
    _loaded[revision] = evidence
    return evidence, 'ci', revision
