"""Command-line acquisition and matching; the core API performs no file I/O."""

from __future__ import annotations

import argparse
import json
from transport_matcher.timing import stage
from pathlib import Path

from transport_matcher.results import write_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description="Match public transport data against OSM and export a result bundle.")
    commands = parser.add_subparsers(dest="command", required=True)
    swiss = commands.add_parser("swiss", help="Run the Swiss ATLAS profile")
    swiss.add_argument("--source", type=Path, help="ATLAS stops CSV")
    swiss.add_argument("--osm", type=Path, help="OSM XML extract")
    swiss.add_argument("--processed", type=Path, help="Optional cached route/identity products")
    swiss.add_argument("--gtfs", type=Path, help="Optional GTFS folder to rebuild routes and identities")
    swiss.add_argument("--boundary", type=Path, help="Optional explicit GeoJSON boundary for GTFS filtering")
    swiss.add_argument("--workspace", type=Path, help="Acquisition workspace containing data/raw and data/processed")
    swiss.add_argument("--download", action="store_true", help="Refresh Swiss source snapshots in the workspace")
    swiss.add_argument("--force", action="store_true", help="Rebuild cached source products")
    swiss.add_argument("--output", required=True, type=Path, help="New result directory (must not exist)")
    gtfs = commands.add_parser("gtfs", help="Run a generic GTFS feed without Swiss identifiers")
    gtfs.add_argument("--source", required=True, type=Path, help="GTFS directory or ZIP")
    gtfs.add_argument("--namespace", required=True, help="Stable agency/feed namespace")
    gtfs.add_argument("--osm", required=True, type=Path)
    gtfs.add_argument("--output", required=True, type=Path)
    for command in (swiss, gtfs):
        command.add_argument('--compression-level', type=int, choices=range(10), default=1,
                             help='Bundle gzip level, 0–9 (default: 1 for faster publication)')
    args = parser.parse_args(argv)
    metadata = {}
    if args.command == "swiss":
        from transport_matcher.swiss import run_matching
        workspace = args.workspace.resolve() if args.workspace else None
        if args.download:
            if workspace is None:
                parser.error("--download requires --workspace")
            from transport_matcher.adapters.acquisition import refresh_swiss
            metadata["acquisition"] = refresh_swiss(workspace, force=args.force)
        if workspace:
            args.source = args.source or workspace / "data/raw/stops_ATLAS.csv"
            args.osm = args.osm or workspace / "data/raw/osm_data.xml"
            args.processed = args.processed or workspace / "data/processed"
            boundary = workspace / "data/raw/switzerland.geojson"
            args.boundary = args.boundary or (boundary if boundary.exists() else None)
        if not args.source or not args.osm:
            parser.error("swiss requires --source and --osm, or --workspace")
        result = run_matching(args.source, args.osm, args.processed, args.gtfs, boundary_geojson=args.boundary)
    else:
        from transport_matcher.adapters.gtfs import run_gtfs
        result = run_gtfs(args.source, args.osm, namespace=args.namespace)
    from transport_matcher.statistics import compute_quality_metrics
    with stage("bundle.quality_metrics"):
        result.extensions["quality_metrics"] = compute_quality_metrics(result.matched, result.all_osm_nodes, result.osm_stop_units)
    with stage('bundle.export_validate'):
        path = write_bundle(result, args.output, metadata=metadata, compresslevel=args.compression_level)
    print(json.dumps({"event": "result_published", "path": str(path)}))


if __name__ == "__main__":
    main()
