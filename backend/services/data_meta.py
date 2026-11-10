import os
from typing import Any, Dict

from backend.services.json_files import read_json_object, write_json_atomic

DATA_META_PATH = os.getenv("PIPELINE_DATA_META_PATH", os.path.join("data", "data_meta.json"))


def load_data_meta() -> Dict[str, Any]:
    return read_json_object(DATA_META_PATH)


def save_data_meta(payload: Dict[str, Any]) -> str:
    return write_json_atomic(DATA_META_PATH, payload)


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
        acquisition={key: acquisition[key] for key in ('sources', 'last_overpass_query_at', 'osm_data_at', 'acquired_at')
                     if key in acquisition},
        last_overpass_query_at=acquisition.get('last_overpass_query_at'),
        osm_data_at=acquisition.get('osm_data_at'),
    )
