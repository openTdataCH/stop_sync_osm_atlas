#!/usr/bin/env python3
"""
Performance benchmark for GTFS and HRDF stages on subsets to evaluate
time and memory improvements (streaming GTFS and optimized HRDF parsing).

Usage examples:
  python scripts/perf_bench_subset.py --gtfs-folder data/raw/gtfs \
      --atlas-csv data/raw/stops_ATLAS.csv --run-gtfs --run-hrdf \
      --gtfs-stop-fraction 0.05 --hrdf-sloid-sample 2000

Notes:
  - This script assumes that GTFS and HRDF datasets have been downloaded
    using get_atlas_data.py, or are already present at the given paths.
  - Memory measurement uses resource.ru_maxrss (peak RSS). On macOS this
    is reported in bytes; on some platforms in kilobytes.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
import resource
from typing import Set

import pandas as pd

# Ensure project root is importable when running from scripts/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import helpers from get_atlas_data
from get_atlas_data import (
    load_gtfs_data,
    load_gtfs_data_streaming,
    extract_gtfs_directions,
    extract_route_direction_per_stop,
    match_gtfs_to_atlas,
    build_integrated_gtfs_data_streaming,
    download_and_extract_hrdf,  # not used here, but kept available
    parse_gleise_lv95_for_sloids,
)


def _peak_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # On macOS, ru_maxrss is in bytes; on Linux, it's usually in kilobytes.
    # Try to infer by threshold.
    val = usage.ru_maxrss
    if val < 10_000_000:  # likely kilobytes
        return int(val * 1024)
    return int(val)


def benchmark_gtfs(gtfs_folder: str, atlas_csv: str, stop_fraction: float) -> None:
    print("\n=== GTFS Benchmark ===")
    assert 0 < stop_fraction <= 1.0

    # Load Swiss stops list to sample; if not present, fail fast
    stops_path = os.path.join(gtfs_folder, 'stops.txt')
    if not os.path.exists(stops_path):
        print(f"GTFS stops.txt not found at {stops_path}. Run data download first.")
        return

    stops_df = pd.read_csv(
        stops_path,
        usecols=['stop_id'],
        dtype={'stop_id': str}
    )
    swiss_stop_ids = stops_df[stops_df['stop_id'].str.startswith('85')]['stop_id'].tolist()
    if not swiss_stop_ids:
        print("No Swiss stops found in GTFS stops.txt")
        return

    sample_size = max(1, int(len(swiss_stop_ids) * stop_fraction))
    sampled_stop_ids: Set[str] = set(random.sample(swiss_stop_ids, sample_size))
    print(f"Sampled {len(sampled_stop_ids)} Swiss stop_ids (~{stop_fraction*100:.1f}%)")

    # Load ATLAS traffic points for matching
    if not os.path.exists(atlas_csv):
        print(f"ATLAS CSV not found at {atlas_csv}. Run data download first.")
        return
    traffic_points = pd.read_csv(atlas_csv, sep=';')

    # Baseline approach
    print("\n-- Baseline (in-memory stop_times) --")
    t0 = time.perf_counter()
    mem0 = _peak_rss_bytes()
    baseline = load_gtfs_data(gtfs_folder, stop_id_filter=sampled_stop_ids)
    gtfs_route_directions = extract_gtfs_directions(baseline)
    route_direction_info = extract_route_direction_per_stop(baseline)
    matches = match_gtfs_to_atlas(baseline, traffic_points)
    linked_stops = baseline['stops'].merge(matches, on='stop_id', how='left')
    integrated_baseline = (
        linked_stops
        .merge(route_direction_info, on='stop_id', how='inner')
        .merge(gtfs_route_directions, on='route_id', how='left')
    )
    mem1 = _peak_rss_bytes()
    t1 = time.perf_counter()
    print(f"Baseline integrated rows: {len(integrated_baseline)}")
    print(f"Baseline time: {t1 - t0:.2f}s  | peak RSS delta: {(mem1 - mem0)/1e6:.1f} MB")

    # Streaming approach
    print("\n-- Streaming (two-pass, dedup on the fly) --")
    t2 = time.perf_counter()
    mem2 = _peak_rss_bytes()
    streaming = load_gtfs_data_streaming(gtfs_folder, stop_id_filter=sampled_stop_ids)
    integrated_stream = build_integrated_gtfs_data_streaming(streaming, traffic_points)
    mem3 = _peak_rss_bytes()
    t3 = time.perf_counter()
    print(f"Streaming integrated rows: {len(integrated_stream)}")
    print(f"Streaming time: {t3 - t2:.2f}s | peak RSS delta: {(mem3 - mem2)/1e6:.1f} MB")


def benchmark_hrdf(hrdf_folder: str, atlas_csv: str, sloid_sample: int) -> None:
    print("\n=== HRDF Benchmark (GLEISE_LV95 parsing) ===")
    gleise_path = os.path.join(hrdf_folder, 'GLEISE_LV95')
    if not os.path.exists(gleise_path):
        print(f"GLEISE_LV95 not found at {gleise_path}. Run data download first.")
        return

    if not os.path.exists(atlas_csv):
        print(f"ATLAS CSV not found at {atlas_csv}. Run data download first.")
        return
    traffic_points = pd.read_csv(atlas_csv, sep=';')
    sloids_all = [str(s) for s in traffic_points['sloid'].dropna().astype(str).unique().tolist()]
    if not sloids_all:
        print("No ATLAS sloids found.")
        return

    sample_size = min(max(1, sloid_sample), len(sloids_all))
    sample_sloids = set(random.sample(sloids_all, sample_size))
    print(f"Sampled {len(sample_sloids)} sloids for HRDF parsing test")

    # Baseline (single-pass, no guards)
    print("\n-- Baseline (single-pass, no fast guards) --")
    t0 = time.perf_counter()
    mem0 = _peak_rss_bytes()
    sloid_to_trips_baseline = parse_gleise_lv95_for_sloids(
        hrdf_folder, sample_sloids, two_pass=False, use_fast_guard=False
    )
    mem1 = _peak_rss_bytes()
    t1 = time.perf_counter()
    print(f"Baseline sloids with trips: {len(sloid_to_trips_baseline)}")
    print(f"Baseline time: {t1 - t0:.2f}s  | peak RSS delta: {(mem1 - mem0)/1e6:.1f} MB")

    # Optimized (two-pass with fast guards)
    print("\n-- Optimized (two-pass, fast guards) --")
    t2 = time.perf_counter()
    mem2 = _peak_rss_bytes()
    sloid_to_trips_opt = parse_gleise_lv95_for_sloids(
        hrdf_folder, sample_sloids, two_pass=True, use_fast_guard=True
    )
    mem3 = _peak_rss_bytes()
    t3 = time.perf_counter()
    print(f"Optimized sloids with trips: {len(sloid_to_trips_opt)}")
    print(f"Optimized time: {t3 - t2:.2f}s | peak RSS delta: {(mem3 - mem2)/1e6:.1f} MB")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark GTFS and HRDF performance on subsets")
    parser.add_argument('--gtfs-folder', type=str, default='data/raw/gtfs', help='Path to GTFS folder')
    parser.add_argument('--atlas-csv', type=str, default='data/raw/stops_ATLAS.csv', help='Path to ATLAS stops CSV')
    parser.add_argument('--hrdf-folder', type=str, default='data/raw', help='Path to HRDF folder containing GLEISE_LV95')
    parser.add_argument('--gtfs-stop-fraction', type=float, default=0.05, help='Fraction of Swiss stop_ids to sample [0,1]')
    parser.add_argument('--hrdf-sloid-sample', type=int, default=2000, help='Number of sloids to sample for HRDF benchmark')
    parser.add_argument('--run-gtfs', action='store_true', help='Run GTFS benchmarks')
    parser.add_argument('--run-hrdf', action='store_true', help='Run HRDF benchmarks')
    args = parser.parse_args()

    if not args.run_gtfs and not args.run_hrdf:
        print("Nothing to do. Use --run-gtfs and/or --run-hrdf.")
        sys.exit(0)

    if args.run_gtfs:
        benchmark_gtfs(args.gtfs_folder, args.atlas_csv, args.gtfs_stop_fraction)
    if args.run_hrdf:
        benchmark_hrdf(args.hrdf_folder, args.atlas_csv, args.hrdf_sloid_sample)


if __name__ == '__main__':
    main()


