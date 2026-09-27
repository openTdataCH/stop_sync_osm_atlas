import json
import os
import tempfile
from typing import Any, Dict

DATA_META_PATH = os.getenv("PIPELINE_DATA_META_PATH", os.path.join("data", "data_meta.json"))


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_data_meta() -> Dict[str, Any]:
    try:
        with open(DATA_META_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_data_meta(payload: Dict[str, Any]) -> str:
    _ensure_parent_dir(DATA_META_PATH)
    parent = os.path.dirname(DATA_META_PATH) or "."
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=parent, delete=False) as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = handle.name
    os.replace(temp_path, DATA_META_PATH)
    return DATA_META_PATH


def update_data_meta(**fields: Any) -> Dict[str, Any]:
    payload = load_data_meta()
    payload.update(fields)
    save_data_meta(payload)
    return payload


def record_bundle_metadata(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Record provenance from the published bundle, never a newer workspace feed."""
    metadata = manifest.get('metadata') or {}
    acquisition = metadata.get('acquisition') or {}
    if not isinstance(acquisition, dict):
        acquisition = {}
    return update_data_meta(
        active_run_id=manifest['run_id'],
        source_capabilities=metadata.get('capabilities', []),
        acquisition={key: acquisition[key] for key in ('sources', 'last_overpass_query_at', 'acquired_at')
                     if key in acquisition},
        last_overpass_query_at=acquisition.get('last_overpass_query_at'),
    )
