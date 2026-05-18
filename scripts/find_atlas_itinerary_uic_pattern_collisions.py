#!/usr/bin/env python3
"""Find ATLAS itinerary buckets that contain multiple distinct UIC stop patterns."""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from matching_and_import_db.downloader.get_atlas_data import (
    _atlas_itinerary_bucket_key,
    _iter_trip_groups_from_staged_stop_times,
    _safe_direction_id,
)


DEFAULT_GTFS_DIR = Path("data/raw/gtfs")
DEFAULT_SUMMARY_OUTPUT = Path("data/debug/atlas_itinerary_uic_pattern_collisions_summary.csv")
DEFAULT_PATTERN_OUTPUT = Path("data/debug/atlas_itinerary_uic_pattern_collisions_patterns.csv")


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_uic_from_gtfs_stop_id(stop_id: object) -> str | None:
    if stop_id is None or pd.isna(stop_id):
        return None
    prefix = str(stop_id).strip().split(':', 1)[0]
    return prefix if prefix.isdigit() else None


def _stop_sequence_key(stop_id: str, original_stop_id: object) -> str:
    uic_number = _parse_uic_from_gtfs_stop_id(original_stop_id) or _parse_uic_from_gtfs_stop_id(stop_id)
    if uic_number:
        return f"uic:{uic_number}"
    return f"gtfs:{stop_id}"


def _hash_stop_sequence(stop_keys: list[str]) -> str:
    digest = hashlib.sha1(">".join(stop_keys).encode("utf-8")).hexdigest()
    return digest[:16]


def _load_trip_meta(trips_path: Path) -> dict[str, dict[str, object]]:
    trips = pd.read_csv(
        trips_path,
        usecols=["trip_id", "route_id", "direction_id", "trip_headsign", "trip_short_name"],
        dtype={
            "trip_id": str,
            "route_id": str,
            "trip_headsign": str,
            "trip_short_name": str,
        },
        low_memory=False,
    )
    trips["direction_id"] = pd.to_numeric(trips["direction_id"], errors="coerce").astype("Int64")
    return trips.drop_duplicates(subset=["trip_id"]).set_index("trip_id").to_dict(orient="index")


def _load_stop_original_ids(stops_path: Path) -> dict[str, object]:
    stops = pd.read_csv(
        stops_path,
        usecols=["stop_id", "original_stop_id", "stop_name"],
        dtype={"stop_id": str, "original_stop_id": str, "stop_name": str},
        low_memory=False,
    )
    stops = stops.drop_duplicates(subset=["stop_id"])
    return stops.set_index("stop_id")["original_stop_id"].to_dict()


def analyze_bucket_patterns(gtfs_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    trip_meta = _load_trip_meta(gtfs_dir / "trips.txt")
    stop_original_ids = _load_stop_original_ids(gtfs_dir / "stops.txt")
    stop_times_path = gtfs_dir / "swiss_trip_stop_times.csv"

    bucket_trip_counts: Counter[tuple[str, str | None, str]] = Counter()
    bucket_pattern_counts: dict[tuple[str, str | None, str], Counter[str]] = {}
    bucket_labels: dict[tuple[str, str | None, str], tuple[str | None, str | None]] = {}

    for trip_id, trip_group in _iter_trip_groups_from_staged_stop_times(str(stop_times_path)):
        meta = trip_meta.get(str(trip_id))
        if meta is None:
            continue

        route_id = str(meta.get("route_id"))
        direction_id = _safe_direction_id(meta.get("direction_id"))
        representative_headsign = _first_non_empty(meta.get("trip_headsign"))
        trip_short_name = _first_non_empty(meta.get("trip_short_name"))
        sequence_keys = [
            _stop_sequence_key(str(stop_id), stop_original_ids.get(str(stop_id)))
            for stop_id in trip_group["stop_id"]
        ]
        if not sequence_keys:
            continue

        pattern_hash = _hash_stop_sequence(sequence_keys)
        bucket_key = _atlas_itinerary_bucket_key(representative_headsign, trip_short_name, pattern_hash)
        uic_pattern = ">".join(key.removeprefix("uic:") for key in sequence_keys)

        bucket_id = (route_id, direction_id, bucket_key)
        bucket_trip_counts[bucket_id] += 1
        bucket_pattern_counts.setdefault(bucket_id, Counter())[uic_pattern] += 1
        bucket_labels.setdefault(bucket_id, (representative_headsign, trip_short_name))

    summary_rows: list[dict[str, object]] = []
    pattern_rows: list[dict[str, object]] = []
    affected_trips = 0
    for bucket_id, pattern_counts in bucket_pattern_counts.items():
        route_id, direction_id, bucket_key = bucket_id
        representative_headsign, trip_short_name = bucket_labels[bucket_id]
        trip_count = bucket_trip_counts[bucket_id]
        distinct_uic_patterns = len(pattern_counts)
        if distinct_uic_patterns <= 1:
            continue

        affected_trips += trip_count
        summary_rows.append(
            {
                "route_id": route_id,
                "direction_id": direction_id,
                "bucket_key": bucket_key,
                "representative_headsign": representative_headsign,
                "trip_short_name": trip_short_name,
                "trip_count": trip_count,
                "distinct_uic_patterns": distinct_uic_patterns,
            }
        )
        for uic_pattern, pattern_trip_count in pattern_counts.most_common():
            pattern_rows.append(
                {
                    "route_id": route_id,
                    "direction_id": direction_id,
                    "bucket_key": bucket_key,
                    "uic_pattern": uic_pattern,
                    "pattern_trip_count": pattern_trip_count,
                }
            )

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values(
            by=["distinct_uic_patterns", "trip_count", "route_id", "direction_id", "bucket_key"],
            ascending=[False, False, True, True, True],
        ).reset_index(drop=True)
    else:
        summary = pd.DataFrame(
            columns=[
                "route_id",
                "direction_id",
                "bucket_key",
                "representative_headsign",
                "trip_short_name",
                "trip_count",
                "distinct_uic_patterns",
            ]
        )

    patterns = pd.DataFrame(pattern_rows)
    if not patterns.empty:
        patterns = patterns.sort_values(
            by=["route_id", "direction_id", "bucket_key", "pattern_trip_count", "uic_pattern"],
            ascending=[True, True, True, False, True],
        ).reset_index(drop=True)
    else:
        patterns = pd.DataFrame(
            columns=[
                "route_id",
                "direction_id",
                "bucket_key",
                "uic_pattern",
                "pattern_trip_count",
            ]
        )

    return summary, patterns, len(bucket_pattern_counts), affected_trips


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find current ATLAS itinerary buckets that collapse multiple distinct UIC stop patterns."
    )
    parser.add_argument(
        "--gtfs-dir",
        type=Path,
        default=DEFAULT_GTFS_DIR,
        help="Directory containing trips.txt, stops.txt, and swiss_trip_stop_times.csv",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_SUMMARY_OUTPUT,
        help="CSV path for affected itinerary bucket summary rows",
    )
    parser.add_argument(
        "--pattern-output",
        type=Path,
        default=DEFAULT_PATTERN_OUTPUT,
        help="CSV path for per-pattern detail rows",
    )
    parser.add_argument(
        "--example-limit",
        type=int,
        default=10,
        help="How many affected buckets to print to stdout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary, patterns, total_buckets, affected_trips = analyze_bucket_patterns(args.gtfs_dir)

    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.pattern_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    patterns.to_csv(args.pattern_output, index=False)

    print(f"GTFS dir: {args.gtfs_dir}")
    print(f"Total itinerary buckets: {total_buckets}")
    print(f"Buckets with multiple distinct UIC patterns: {len(summary)}")
    print(f"Affected trips: {affected_trips}")
    print(f"Summary CSV: {args.summary_output}")
    print(f"Pattern CSV: {args.pattern_output}")

    if summary.empty:
        print("No itinerary buckets with multiple UIC stop patterns were found.")
        return 0

    print("Examples:")
    for row in summary.head(args.example_limit).to_dict(orient="records"):
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())