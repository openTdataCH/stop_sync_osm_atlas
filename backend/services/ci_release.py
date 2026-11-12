"""Files CI publishes for each commit of main, as assets of the ``quality-data`` release.

A release asset can be downloaded by anybody; a CI artifact needs a GitHub token, even from a public repository.
"""
from __future__ import annotations

import requests

ASSET_URL = 'https://github.com/openTdataCH/stop_sync_osm_atlas/releases/download/quality-data/{name}'


def download(name, max_bytes):
    """The asset ``name`` as bytes; None when it is missing, larger than ``max_bytes`` or GitHub cannot be reached."""
    body = b''
    try:
        response = requests.get(ASSET_URL.format(name=name), timeout=10, stream=True)
        if response.status_code != 200:
            return None
        for chunk in response.iter_content(1 << 16):
            body += chunk
            if len(body) > max_bytes:
                return None
    except requests.RequestException:
        return None
    return body
