from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from matching_and_import_db.downloader.get_atlas_data import write_atlas_route_csvs
from matching_and_import_db.downloader.get_atlas_gtfs import (
    build_gtfs_atlas_payload,
    build_integrated_gtfs_data_streaming,
    parse_gtfs_stop_ids,
    write_gtfs_db_payload_cache,
)
from matching_and_import_db.downloader.get_osm_data import process_osm_routes_data


def _hash_keep(value: str, fraction: float) -> bool:
    if fraction >= 1.0:
        return True
    digest = hashlib.sha1(value.encode('utf-8')).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return bucket < fraction


def _sample_atlas(atlas_source: Path, atlas_output: Path, atlas_fraction: float) -> tuple[pd.DataFrame, set[str]]:
    atlas_df = pd.read_csv(atlas_source, sep=';', dtype=str, low_memory=False)
    atlas_df = atlas_df.sort_values(by=['number', 'sloid'], na_position='last').reset_index(drop=True)

    unique_uics = [value for value in atlas_df['number'].dropna().astype(str).unique().tolist() if value]
    keep_count = max(1, int(len(unique_uics) * atlas_fraction))
    selected_uics = set(unique_uics[:keep_count])
    sampled_atlas = atlas_df[atlas_df['number'].astype(str).isin(selected_uics)].copy()

    atlas_output.parent.mkdir(parents=True, exist_ok=True)
    sampled_atlas.to_csv(atlas_output, sep=';', index=False)
    return sampled_atlas, selected_uics


def _prepare_sample_gtfs(
    gtfs_source_dir: Path,
    gtfs_output_dir: Path,
    selected_uics: set[str],
    trip_fraction: float,
    max_trips_per_route_direction: int,
) -> tuple[Path, dict[str, int]]:
    gtfs_output_dir.mkdir(parents=True, exist_ok=True)

    stops_columns = [
        'stop_id', 'stop_name', 'stop_lat', 'stop_lon', 'stop_code',
        'platform_code', 'original_stop_id', 'location_type', 'parent_station',
    ]
    stops_df = pd.read_csv(
        gtfs_source_dir / 'stops.txt',
        usecols=lambda column_name: column_name in set(stops_columns),
        dtype=str,
        low_memory=False,
    )
    parsed_stops = parse_gtfs_stop_ids(stops_df)
    sampled_seed_stops = parsed_stops[parsed_stops['uic_number'].astype(str).isin(selected_uics)].copy()
    if sampled_seed_stops.empty:
        raise RuntimeError('No GTFS stops matched the sampled ATLAS UIC subset.')

    seed_stop_ids = set(sampled_seed_stops['stop_id'].dropna().astype(str))

    relevant_trip_ids: set[str] = set()
    stop_times_path = gtfs_source_dir / 'stop_times.txt'
    for chunk in pd.read_csv(
        stop_times_path,
        usecols=['trip_id', 'stop_id'],
        dtype={'trip_id': str, 'stop_id': str},
        chunksize=500000,
        low_memory=False,
    ):
        mask = chunk['stop_id'].isin(seed_stop_ids)
        if not mask.any():
            continue
        relevant_trip_ids.update(chunk.loc[mask, 'trip_id'].dropna().astype(str).unique())

    retained_trip_ids = {trip_id for trip_id in relevant_trip_ids if _hash_keep(trip_id, trip_fraction)}
    if not retained_trip_ids:
        raise RuntimeError('Trip downsampling removed every relevant trip. Increase --trip-fraction.')

    trips_df = pd.read_csv(gtfs_source_dir / 'trips.txt', dtype=str, low_memory=False)
    sampled_trips = trips_df[trips_df['trip_id'].astype(str).isin(retained_trip_ids)].copy()
    if sampled_trips.empty:
        raise RuntimeError('No sampled GTFS trips remain after filtering.')
    sampled_trips = sampled_trips.sort_values(by=['route_id', 'direction_id', 'trip_id'], na_position='last').reset_index(drop=True)
    if max_trips_per_route_direction > 0:
        sampled_trips = sampled_trips.groupby(['route_id', 'direction_id'], dropna=False, sort=False).head(max_trips_per_route_direction).copy()
    retained_trip_ids = set(sampled_trips['trip_id'].dropna().astype(str))
    sampled_trips.to_csv(gtfs_output_dir / 'trips.txt', index=False)

    retained_route_ids = set(sampled_trips['route_id'].dropna().astype(str))
    routes_df = pd.read_csv(gtfs_source_dir / 'routes.txt', dtype=str, low_memory=False)
    sampled_routes = routes_df[routes_df['route_id'].astype(str).isin(retained_route_ids)].copy()
    sampled_routes.to_csv(gtfs_output_dir / 'routes.txt', index=False)

    referenced_stop_ids: set[str] = set()
    stop_times_out = gtfs_output_dir / 'stop_times.txt'
    wrote_header = False
    for chunk in pd.read_csv(
        stop_times_path,
        dtype={'trip_id': str, 'stop_id': str},
        chunksize=500000,
        low_memory=False,
    ):
        mask = chunk['trip_id'].isin(retained_trip_ids)
        if not mask.any():
            continue
        sampled_chunk = chunk.loc[mask].copy()
        referenced_stop_ids.update(sampled_chunk['stop_id'].dropna().astype(str).unique())
        sampled_chunk.to_csv(stop_times_out, index=False, mode='a', header=not wrote_header)
        wrote_header = True

    sampled_stops = stops_df[stops_df['stop_id'].astype(str).isin(referenced_stop_ids)].copy()
    sampled_stops.to_csv(gtfs_output_dir / 'stops.txt', index=False)

    return gtfs_output_dir, {
        'seed_stops': len(seed_stop_ids),
        'relevant_trips': len(relevant_trip_ids),
        'retained_trips': len(retained_trip_ids),
        'retained_routes': len(retained_route_ids),
        'referenced_stops': len(referenced_stop_ids),
    }


def _generate_sample_workspace(
    workspace_dir: Path,
    atlas_source: Path,
    gtfs_source_dir: Path,
    osm_xml_source: Path,
    atlas_fraction: float,
    trip_fraction: float,
    max_trips_per_route_direction: int,
) -> dict[str, object]:
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)

    raw_dir = workspace_dir / 'data' / 'raw'
    processed_dir = workspace_dir / 'data' / 'processed'
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    sampled_atlas_path = raw_dir / 'stops_ATLAS.csv'
    sampled_atlas_df, selected_uics = _sample_atlas(atlas_source, sampled_atlas_path, atlas_fraction)
    sampled_gtfs_dir, gtfs_stats = _prepare_sample_gtfs(
        gtfs_source_dir=gtfs_source_dir,
        gtfs_output_dir=raw_dir / 'gtfs',
        selected_uics=selected_uics,
        trip_fraction=trip_fraction,
        max_trips_per_route_direction=max_trips_per_route_direction,
    )

    shutil.copy2(osm_xml_source, raw_dir / 'osm_data.xml')
    process_osm_routes_data((raw_dir / 'osm_data.xml').read_text(encoding='utf-8'), str(processed_dir))

    from matching_and_import_db.downloader.get_atlas_gtfs import load_gtfs_data_streaming

    gtfs_stream = load_gtfs_data_streaming(str(sampled_gtfs_dir))
    gtfs_payload = build_gtfs_atlas_payload(gtfs_stream, sampled_atlas_df)

    stats_backup_path = REPO_ROOT / 'data' / 'gtfs_atlas_stats.json'
    stats_backup = stats_backup_path.read_bytes() if stats_backup_path.exists() else None
    try:
        integrated_data = build_integrated_gtfs_data_streaming(gtfs_stream, sampled_atlas_df, gtfs_payload=gtfs_payload)
    finally:
        generated_stats_path = REPO_ROOT / 'data' / 'gtfs_atlas_stats.json'
        workspace_stats_path = workspace_dir / 'data' / 'gtfs_atlas_stats.json'
        workspace_stats_path.parent.mkdir(parents=True, exist_ok=True)
        if generated_stats_path.exists():
            shutil.copy2(generated_stats_path, workspace_stats_path)
        if stats_backup is None:
            try:
                generated_stats_path.unlink()
            except FileNotFoundError:
                pass
        else:
            generated_stats_path.write_bytes(stats_backup)

    write_gtfs_db_payload_cache(
        gtfs_payload,
        sampled_atlas_df,
        stops_cache_path=str(processed_dir / 'gtfs_stops_raw.csv'),
        state_cache_path=str(processed_dir / 'gtfs_stop_identity_resolution.csv'),
    )
    write_atlas_route_csvs(
        gtfs_data=gtfs_stream,
        traffic_points=sampled_atlas_df,
        integrated_gtfs_data=integrated_data,
        out_dir=str(processed_dir),
    )

    return {
        'workspace_dir': workspace_dir,
        'sampled_atlas_rows': len(sampled_atlas_df),
        'sampled_uics': len(selected_uics),
        **gtfs_stats,
    }


def _run_matching_import(workspace_dir: Path, database_uri: str) -> None:
    original_cwd = Path.cwd()
    previous_env = {
        'ATLAS_STOPS_CSV': os.environ.get('ATLAS_STOPS_CSV'),
        'GTFS_FOLDER': os.environ.get('GTFS_FOLDER'),
        'OSM_XML_FILE': os.environ.get('OSM_XML_FILE'),
        'DATABASE_URI': os.environ.get('DATABASE_URI'),
    }

    try:
        os.chdir(workspace_dir)
        os.environ['ATLAS_STOPS_CSV'] = 'data/raw/stops_ATLAS.csv'
        os.environ['GTFS_FOLDER'] = 'data/raw/gtfs'
        os.environ['OSM_XML_FILE'] = 'data/raw/osm_data.xml'
        os.environ['DATABASE_URI'] = database_uri

        import matching_and_import_db.database.session as session_module
        import matching_and_import_db.orchestrator as orchestrator_mod
        import matching_and_import_db.database.importer as importer_mod
        import matching_and_import_db.database.helpers as helpers_mod

        session_module = importlib.reload(session_module)
        helpers_mod = importlib.reload(helpers_mod)
        orchestrator_mod = importlib.reload(orchestrator_mod)
        importer_mod = importlib.reload(importer_mod)

        matching_output = orchestrator_mod.run_matching()
        problem_artifacts = importer_mod.precompute_problem_artifacts(matching_output)
        route_artifacts = importer_mod.precompute_route_artifacts(matching_output)
        db_payloads = importer_mod.build_fast_insert_payloads(matching_output, problem_artifacts, route_artifacts)
        importer_mod.import_to_database(db_payloads=db_payloads)

        print(
            'Sample smoke import completed: '
            f"matched={len(matching_output.matched):,}, "
            f"unmatched_atlas={len(matching_output.unmatched_atlas):,}, "
            f"unmatched_osm={len(matching_output.unmatched_osm):,}"
        )
    finally:
        os.chdir(original_cwd)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description='Run an isolated reduced-data smoke test for the refactored route product.')
    parser.add_argument('--atlas-fraction', type=float, default=0.2, help='Fraction of ATLAS UIC groups to keep.')
    parser.add_argument('--trip-fraction', type=float, default=0.5, help='Deterministic fraction of relevant GTFS trips to keep.')
    parser.add_argument('--max-trips-per-route-direction', type=int, default=4, help='Maximum GTFS trips to keep per (route_id, direction_id) group in the smoke dataset.')
    parser.add_argument('--workspace-dir', default='data/debug/sample_refactor_smoke', help='Workspace directory for the isolated sampled run.')
    parser.add_argument('--database-uri', default=os.environ.get('DATABASE_URI', 'postgresql+psycopg://stops_user:1234@localhost:5432/import_db'))
    args = parser.parse_args()

    workspace_dir = (REPO_ROOT / args.workspace_dir).resolve()
    summary = _generate_sample_workspace(
        workspace_dir=workspace_dir,
        atlas_source=REPO_ROOT / 'data' / 'raw' / 'stops_ATLAS.csv',
        gtfs_source_dir=REPO_ROOT / 'data' / 'raw' / 'gtfs',
        osm_xml_source=REPO_ROOT / 'data' / 'raw' / 'osm_data.xml',
        atlas_fraction=args.atlas_fraction,
        trip_fraction=args.trip_fraction,
        max_trips_per_route_direction=args.max_trips_per_route_direction,
    )
    print('Prepared sample workspace:')
    for key, value in summary.items():
        print(f'  {key}: {value}')

    _run_matching_import(workspace_dir, args.database_uri)


if __name__ == '__main__':
    main()