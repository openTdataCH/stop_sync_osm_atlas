"""Standalone Swiss acquisition, explicit local caches and portable metadata."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from transport_matcher.timing import stage

from .get_atlas_data import ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK, get_atlas_stops, get_current_gtfs_permalink
from .get_atlas_gtfs import download_and_extract_gtfs
from transport_matcher.acquisition.overpass import query_overpass
from .geo_utils import _ensure_swiss_geojson_cache
from .source_freshness import probe_remote_source, source_snapshot_is_unchanged

SWISS_BOUNDARY_URL = 'https://raw.githubusercontent.com/ZHB/switzerland-geojson/master/country/switzerland.geojson'
_CACHE_FILES = (
    'raw/stops_ATLAS.csv',
    'processed/atlas_line_families.csv',
    'processed/atlas_itineraries.csv',
    'processed/atlas_itinerary_stop_calls.csv',
    'processed/gtfs_stops_raw.csv',
    'processed/gtfs_stop_identity_resolution.csv',
)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_files(data_dir, files):
    if not files:
        return False
    for relative, digest in files.items():
        path = (data_dir / relative).resolve()
        if not path.is_relative_to(data_dir) or not path.is_file() or _sha256(path) != digest:
            return False
    return True


def _atlas_is_valid(path):
    frame = pd.read_csv(path, sep=';', dtype=str, usecols=lambda c: c == 'validTo')
    today = datetime.now(timezone.utc).date().isoformat()
    return 'validTo' not in frame or not (frame['validTo'].str.slice(0, 10) < today).any()


def _cache_reason(previous, inputs, data_dir, *, force=False, source=None):
    if force:
        return 'forced'
    if not previous:
        return 'missing_or_old_cache'
    if previous.get('inputs') != inputs:
        return 'inputs_changed'
    if source is not None:
        old = previous.get('source', {})
        if old.get('url') != source.get('url') or not source_snapshot_is_unchanged(old, source):
            return 'source_changed_or_unverifiable'
    if not _verified_files(data_dir, previous.get('files')):
        return 'products_missing_or_changed'
    return 'hit'


def _write_json_atomic(path, value):
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def refresh_swiss(
    workspace: str | Path,
    force: bool = False,
    *,
    atlas_url: str = ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK,
    gtfs_url: str | None = None,
    boundary_url: str = SWISS_BOUNDARY_URL,
    overpass_url: str | None = None,
) -> dict:
    """Refresh a Swiss workspace and return source timestamps and filter metrics.

    All artifacts live below ``workspace/data``. OSM is refreshed each run;
    ATLAS/GTFS preprocessing is reused only with matching HTTP validators and
    verified local products. Staged downloads never overwrite a usable cache
    until preprocessing succeeds. No app status, database or credentials are used.
    """
    data_dir = Path(workspace).resolve() / 'data'
    raw, processed = data_dir / 'raw', data_dir / 'processed'
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    meta_path = data_dir / 'source_metadata.json'
    try:
        previous = json.loads(meta_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        previous = {}
    gtfs_url = gtfs_url or get_current_gtfs_permalink()
    with stage('acquisition.source_probes'):
        snapshots = {
            'atlas': probe_remote_source('ATLAS', atlas_url),
            'gtfs': probe_remote_source('GTFS', gtfs_url),
        }
    boundary = raw / 'switzerland.geojson'
    _ensure_swiss_geojson_cache(str(boundary), download_url=boundary_url)
    boundary_fingerprint = _sha256(boundary)
    from transport_matcher.swiss import _load_gtfs_products, _map_gtfs_products
    from .gtfs_columnar import CACHE_VERSION, read_cache, write_cache
    stages = dict(previous.get('stages', {})) if previous.get('cache_version') == 2 else {}
    metadata = dict(previous)
    metadata.update(cache_version=2, stages=stages)
    backend = os.getenv('GTFS_PROCESSING_BACKEND', 'duckdb')
    decisions = {}

    def decide(name, inputs, source=None):
        reason = _cache_reason(stages.get(name), inputs, data_dir, force=force, source=source)
        if name == 'atlas' and reason == 'hit' and not _atlas_is_valid(raw / 'stops_ATLAS.csv'):
            reason = 'atlas_validity_expired'
        decisions[name] = reason
        print(json.dumps({'event': 'cache_decision', 'stage': name, 'reason': reason}), flush=True)
        return reason == 'hit'

    def checkpoint(name, inputs, paths, source=None):
        stages[name] = {'inputs': inputs, 'files': {
            str(path.relative_to(data_dir)): _sha256(path) for path in paths}, 'source': source}
        # A later OSM/network failure must not discard successful GTFS work.
        _write_json_atomic(meta_path, metadata)

    with TemporaryDirectory(prefix='.acquisition-', dir=data_dir) as staging_name:
        staging = Path(staging_name)
        atlas_inputs = {'boundary': boundary_fingerprint, 'version': 1}
        if not decide('atlas', atlas_inputs, snapshots['atlas']):
            with stage('acquisition.atlas'):
                atlas_path = staging / 'stops_ATLAS.csv'
                metadata['atlas_filtering'] = get_atlas_stops(atlas_path, atlas_url, boundary_geojson=boundary)
                os.replace(atlas_path, raw / 'stops_ATLAS.csv')
                checkpoint('atlas', atlas_inputs, [raw / 'stops_ATLAS.csv'], snapshots['atlas'])

        gtfs_inputs = {'boundary': boundary_fingerprint, 'version': CACHE_VERSION, 'backend': backend}
        cache_dir = data_dir / 'cache' / 'gtfs'
        prepared_gtfs = None
        if not decide('gtfs', gtfs_inputs, snapshots['gtfs']):
            source_inputs = {'version': 1}
            if not decide('gtfs_source', source_inputs, snapshots['gtfs']):
                with stage('acquisition.gtfs_download_extract'):
                    gtfs_folder = Path(download_and_extract_gtfs(gtfs_url, str(staging / 'gtfs')))
                    target = raw / 'gtfs'
                    target.mkdir(exist_ok=True)
                    for name in ('stops.txt', 'trips.txt', 'routes.txt', 'stop_times.txt'):
                        os.replace(gtfs_folder / name, target / name)
                    checkpoint('gtfs_source', source_inputs,
                               [target / name for name in ('stops.txt', 'trips.txt', 'routes.txt', 'stop_times.txt')], snapshots['gtfs'])
            # Large working tables stay on the container temporary filesystem.
            with TemporaryDirectory(prefix='transport-matcher-gtfs-') as scratch:
                gtfs = _load_gtfs_products(raw / 'gtfs', boundary, scratch)
                pending = staging / 'gtfs_cache'
                with stage('gtfs.cache_write'):
                    write_cache(gtfs, pending)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    products = list(pending.iterdir())
                    for product in products:
                        os.replace(product, cache_dir / product.name)
                    checkpoint('gtfs', gtfs_inputs, [cache_dir / product.name for product in products], snapshots['gtfs'])
                    # Reuse in-memory metadata on a fresh run; only the pattern
                    # path must move out of scratch before it is removed.
                    if gtfs.get('trip_patterns_path'):
                        gtfs['trip_patterns_path'] = str(cache_dir / 'trip_patterns.parquet')
                    if gtfs.get('trip_stop_times_path'):
                        gtfs['trip_stop_times_path'] = str(cache_dir / 'trip_stop_times.csv')
                    prepared_gtfs = gtfs

        mapping_inputs = {'atlas': stages['atlas']['files'], 'gtfs': stages['gtfs']['files'], 'version': 1}
        mapping_reused = decide('gtfs_atlas', mapping_inputs)
        if not mapping_reused:
            if prepared_gtfs is None:
                with stage('gtfs.cache_read'):
                    prepared_gtfs = read_cache(cache_dir)
            traffic_points = pd.read_csv(raw / 'stops_ATLAS.csv', sep=';', dtype=str)
            route_data, stops, identities, mapping_stats = _map_gtfs_products(prepared_gtfs, traffic_points)
            with stage('gtfs.write_products'):
                for key, frame in route_data.items():
                    frame.to_csv(staging / f'{key}.csv', index=False)
                pd.DataFrame(stops).to_csv(staging / 'gtfs_stops_raw.csv', index=False)
                identity_frame = pd.DataFrame(identities)
                if 'details_json' in identity_frame:
                    identity_frame['details_json'] = identity_frame['details_json'].map(json.dumps)
                identity_frame.to_csv(staging / 'gtfs_stop_identity_resolution.csv', index=False)
                for relative in _CACHE_FILES[1:]:
                    destination = data_dir / relative
                    os.replace(staging / destination.name, destination)
                metadata['gtfs_atlas_statistics'] = mapping_stats
                checkpoint('gtfs_atlas', mapping_inputs, [data_dir / relative for relative in _CACHE_FILES[1:]])
        prepared_gtfs = None
        gtfs = None
        with stage('acquisition.osm'):
            query_overpass(output_path=str(staging / 'osm_data.xml'), overpass_url=overpass_url)
            os.replace(staging / 'osm_data.xml', raw / 'osm_data.xml')
        # Route products are derived once by run_matching from this exact XML.
    now = datetime.now(timezone.utc).isoformat()
    metadata.update({
        'sources': snapshots, 'acquired_at': now, 'boundary_sha256': boundary_fingerprint,
        'last_overpass_query_at': now, 'preprocessing_reused': mapping_reused,
        'cache_decisions': decisions,
        'attribution': {'source': 'opentransportdata.swiss', 'osm': '© OpenStreetMap contributors, ODbL'},
    })
    _write_json_atomic(meta_path, metadata)
    return metadata
