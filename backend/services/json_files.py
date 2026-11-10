"""JSON files under data/: the shared runtime state directory, reads, atomic writes and a cross-process lock."""

import json
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, Iterator

DEFAULT_STATE_DIR = os.path.join("data", "runtime")


def resolve_state_dir() -> str:
    """Directory shared by the app, scheduler and runner for pipeline status, run lease and export tasks."""
    return os.getenv("STATE_DIR", DEFAULT_STATE_DIR)


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def read_json_object(path: str) -> Dict[str, Any]:
    """The JSON object stored at path, or {} when the file is missing, unreadable or not an object."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json_atomic(path: str, payload: Any, **dump_options: Any) -> str:
    """Write payload so readers see either the old file or the complete new one, never a partial file."""
    ensure_parent_dir(path)
    parent = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=parent, delete=False) as handle:
        json.dump(payload, handle, **dump_options)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = handle.name
    os.replace(temp_path, path)
    return path


@contextmanager
def exclusive_file_lock(path: str) -> Iterator[None]:
    """Hold an exclusive lock on path, shared by every process that mounts the same directory."""
    import fcntl

    ensure_parent_dir(path)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
