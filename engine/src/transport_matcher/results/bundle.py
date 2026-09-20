"""Serialize complete matching runs without application or persistence imports."""

from __future__ import annotations

import gzip
import ctypes
import errno
import sys
import hashlib
import json
import math
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

SCHEMA_VERSION = 1
SECTIONS = (
    "source_stops", "osm_nodes", "matches", "unmatched", "groups",
    "problems", "routes", "extensions", "diagnostics",
)


def _json_value(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [_json_value(v) for v in sorted(value)]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _osm_key(node):
    return node.key


def _sections(result):
    sources = {node.key: node for node in result.all_source_nodes}
    for match in result.matched:
        sources[match.source_node.key] = match.source_node
    for node in result.unmatched_source:
        sources[node.key] = node
    osm = {_osm_key(node): node for node in result.all_osm_nodes}
    for match in result.matched:
        osm[_osm_key(match.osm_node)] = match.osm_node
    for node in result.unmatched_osm:
        osm[_osm_key(node)] = node

    def source_rows():
        for key, node in sorted(sources.items()):
            yield {**_json_value(node), "key": key}

    def osm_rows():
        for key, node in sorted(osm.items()):
            yield {**_json_value(node), "key": key}

    def match_rows():
        for match in result.matched:
            yield {
                "source_key": match.source_node.key,
                "osm_key": _osm_key(match.osm_node),
                "method": match.match_type,
                "distance_m": match.distance_m,
                "notes": match.notes,
                "evidence": getattr(match, "evidence", {}),
                "problems": _json_value(match.problems),
            }

    def unmatched_rows():
        isolated_source = set(getattr(result, "source_isolated_keys", []))
        isolated_osm = set(getattr(result, "isolated_osm_ids", []))
        effective = set(getattr(result, "effectively_matched_osm_ids", []))
        for node in result.unmatched_source:
            yield {"side": "source", "key": node.key, "isolated": node.key in isolated_source}
        for node in result.unmatched_osm:
            yield {
                "side": "osm", "key": _osm_key(node),
                "isolated": str(node.node_id) in isolated_osm,
                "effectively_matched": str(node.node_id) in effective,
            }

    def group_rows():
        seen = set()
        for key, members in sorted(result.duplicate_key_map.items()):
            identity = tuple(sorted(members))
            if identity in seen:
                continue
            seen.add(identity)
            yield {"side": "source", "key": identity[0], "members": list(identity), "kind": "duplicate"}
        for unit in result.osm_stop_units:
            yield {"side": "osm", **_json_value(unit)}

    extensions = dict(getattr(result, "extensions", {}) or {})
    extensions["duplicate_osm_group_map"] = result.duplicate_osm_group_map
    # Route evidence is part of the portable result, rather than a shared file path.
    extensions["route_evidence"] = {
        "source": result.source_route_evidence_by_key,
        "osm": result.osm_node_routes,
        "osm_name_directions": result.osm_name_dirs,
    }
    return {
        "source_stops": source_rows(), "osm_nodes": osm_rows(),
        "matches": match_rows(), "unmatched": unmatched_rows(), "groups": group_rows(),
        "problems": iter(result.problems),
        "routes": ({"kind": k, "value": v} for k, v in sorted((getattr(result, "routes", {}) or {}).items())),
        "extensions": ({"kind": k, "value": v} for k, v in sorted(extensions.items())),
        "diagnostics": iter(result.diagnostics),
    }


def fingerprint(path):
    """Content identity for a source snapshot, independent of its local path."""
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"name": path.name, "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def _publish_directory(temporary, destination):
    """Atomically rename a directory without replacing even an empty target."""
    if sys.platform == 'win32':
        os.rename(temporary, destination)  # Windows rename never replaces a target.
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(temporary), os.fsencode(destination), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(library, 'renameat2'):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(temporary), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise OSError(errno.ENOSYS, 'Atomic exclusive directory publication is unsupported on this platform')
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def write_bundle(result, destination, *, metadata=None, compresslevel=1):
    """Publish a complete new run directory atomically; never overwrite a run."""
    if not isinstance(compresslevel, int) or not 0 <= compresslevel <= 9:
        raise ValueError('compresslevel must be an integer between 0 and 9')
    from .validation import validate_output, validate_bundle
    validate_output(result)
    if 'quality_metrics' not in result.extensions:
        from transport_matcher.statistics import compute_quality_metrics
        result.extensions['quality_metrics'] = compute_quality_metrics(result.matched, result.all_osm_nodes, result.osm_stop_units)
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Result destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".matching-", dir=destination.parent))
    try:
        try:
            engine_version = version("transport-matcher")
        except PackageNotFoundError:
            engine_version = "0.1.0"
        manifest = {
            "schema_version": SCHEMA_VERSION, "engine_version": engine_version,
            "run_id": str(uuid.uuid4()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile_id": result.profile_id,
            "metadata": {**getattr(result, "metadata", {}), **(metadata or {})},
            "files": {},
        }
        for section, rows in _sections(result).items():
            name = f"{section}.jsonl.gz"
            count = 0
            with (temporary / name).open("wb") as raw:
                with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=compresslevel) as zipped:
                    for row in rows:
                        zipped.write((json.dumps(_json_value(row), ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
                        count += 1
                raw.flush()
                os.fsync(raw.fileno())
            manifest["files"][section] = {
                "name": name, "rows": count,
                **{k: v for k, v in fingerprint(temporary / name).items() if k != "name"},
            }
        with (temporary / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(_json_value(manifest), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        validate_bundle(temporary)
        _publish_directory(temporary, destination)
        return destination
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
