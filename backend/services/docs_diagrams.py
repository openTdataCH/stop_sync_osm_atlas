"""The documentation PDF's Mermaid diagrams, as CI rendered them for the commit this code runs at.

Rendering needs Node and a browser. The Docker image renders them while it is built; a server without Docker downloads
the set the Quality workflow published for its commit, once.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import tarfile
import time

from backend.services import ci_release
from backend.version import app_revision

MAX_BYTES = 16 * 1024 * 1024
# After GitHub had no set for a commit, ask again only this many seconds later, not for every PDF.
RETRY_SECONDS = 300
DIAGRAM_NAME = re.compile(r'mermaid-[0-9a-f]{16}\.svg')


def fetch(directory) -> bool:
    """Add the diagrams CI rendered for this code's commit to ``directory``; True when the set was there.

    The set of a commit never changes, so after one download it is not asked for again. Only files named like a
    rendered diagram are taken from the archive.
    """
    revision = app_revision()
    if revision is None:
        return False
    directory = Path(directory)
    marker = directory / f'.ci-{revision}'
    try:
        if marker.read_text() == 'fetched' or time.time() - marker.stat().st_mtime < RETRY_SECONDS:
            return False
    except OSError:
        pass
    diagrams = _diagrams(ci_release.download(f'diagrams-{revision}.tar.gz', MAX_BYTES))
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for name, svg in diagrams.items():
            # Written beside the final name and renamed, so another build never reads half a file.
            temporary = directory / f'{name}.{os.getpid()}.tmp'
            temporary.write_bytes(svg)
            temporary.replace(directory / name)
        marker.write_text('fetched' if diagrams else 'missing')
    except OSError:
        return False
    return bool(diagrams)


def _diagrams(archive) -> dict[str, bytes]:
    """The rendered diagrams in a downloaded ``.tar.gz``, by file name; empty when there is none or it is unreadable."""
    if not archive:
        return {}
    diagrams = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            for member in tar:
                if member.isfile() and DIAGRAM_NAME.fullmatch(member.name):
                    diagrams[member.name] = tar.extractfile(member).read()
    except (tarfile.TarError, OSError, EOFError):
        return {}
    return diagrams
