import os
import re
from typing import Any, Dict
from urllib.parse import urlparse

import requests


_FILENAME_RE = re.compile(r'filename="?([^";]+)"?')
_PROBE_TIMEOUT_SECONDS = int(os.getenv("PIPELINE_SOURCE_PROBE_TIMEOUT_SECONDS", "120"))


def _strip_query(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()


def _extract_filename(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None
    match = _FILENAME_RE.search(content_disposition)
    if not match:
        return None
    return match.group(1)


def probe_remote_source(label: str, url: str, timeout_seconds: int = _PROBE_TIMEOUT_SECONDS) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "label": label,
        "url": url,
        "probe_ok": False,
    }

    try:
        with requests.get(
            url,
            allow_redirects=True,
            stream=True,
            timeout=timeout_seconds,
            headers={"Range": "bytes=0-0"},
        ) as response:
            response.raise_for_status()
            content_disposition = response.headers.get("Content-Disposition")
            snapshot.update(
                {
                    "probe_ok": True,
                    "status_code": response.status_code,
                    "final_url": _strip_query(response.url),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_length": response.headers.get("Content-Length"),
                    "content_disposition": content_disposition,
                    "download_filename": _extract_filename(content_disposition),
                }
            )
    except requests.RequestException as exc:
        snapshot["error"] = str(exc)

    return snapshot


def source_snapshot_is_usable(snapshot: Dict[str, Any] | None) -> bool:
    if not snapshot or not snapshot.get("probe_ok"):
        return False
    return any(snapshot.get(key) for key in ("etag", "last_modified", "download_filename", "final_url"))


def source_snapshot_is_unchanged(previous: Dict[str, Any] | None, current: Dict[str, Any] | None) -> bool:
    if not source_snapshot_is_usable(previous) or not source_snapshot_is_usable(current):
        return False

    for key in ("etag", "last_modified", "download_filename", "final_url"):
        previous_value = previous.get(key)
        current_value = current.get(key)
        if previous_value and current_value:
            return previous_value == current_value

    return False


def preprocessing_sources_unchanged(
    previous_sources: Dict[str, Any] | None,
    current_sources: Dict[str, Any] | None,
) -> bool:
    if not previous_sources or not current_sources:
        return False

    for source_name in ("atlas", "gtfs"):
        if not source_snapshot_is_unchanged(previous_sources.get(source_name), current_sources.get(source_name)):
            return False

    return True