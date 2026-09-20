"""Offline GTFS benchmark. Run each backend in a separate, otherwise idle process.

python engine/benchmarks/gtfs.py --gtfs data/raw/gtfs --atlas data/raw/stops_ATLAS.csv \
    --boundary data/raw/switzerland.geojson --backend duckdb --report /tmp/gtfs-native.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import pandas as pd


def product_hash(rows):
    # Compare content independently of DataFrame/index or export row ordering.
    encoded = sorted(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) for row in rows)
    return hashlib.sha256(('\n'.join(encoded)).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gtfs', required=True, type=Path)
    parser.add_argument('--atlas', required=True, type=Path)
    parser.add_argument('--boundary', type=Path)
    parser.add_argument('--backend', choices=['pandas', 'duckdb'], required=True)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--compare', type=Path, help='Fail if output hashes differ from a previous report')
    args = parser.parse_args()
    os.environ['GTFS_PROCESSING_BACKEND'] = args.backend
    from transport_matcher.swiss import _fresh_gtfs_products
    started, cpu = time.perf_counter(), time.process_time()
    products, stops, identities, stats = _fresh_gtfs_products(
        args.gtfs, pd.read_csv(args.atlas, sep=';', dtype=str), args.boundary)
    seconds, cpu_seconds = time.perf_counter() - started, time.process_time() - cpu
    products = {name: frame.astype(object).where(frame.notna(), None).to_dict('records')
                for name, frame in products.items()}
    products.update(gtfs_stops=stops, gtfs_identity=identities)
    report = {'backend': args.backend, 'seconds': seconds, 'cpu_seconds': cpu_seconds,
              'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
              'input_bytes': {p.name: p.stat().st_size for p in args.gtfs.glob('*.txt')},
              'rows': {name: len(rows) for name, rows in products.items()},
              'product_hashes': {name: product_hash(rows) for name, rows in products.items()},
              'mapping_statistics': stats}
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'event': 'benchmark_finished', 'report': str(args.report), 'seconds': seconds}), flush=True)
    if args.compare:
        previous = json.loads(args.compare.read_text())
        if report['product_hashes'] != previous['product_hashes']:
            raise SystemExit('GTFS product parity failed; compare the report hashes before accepting timings')


if __name__ == '__main__':
    main()
