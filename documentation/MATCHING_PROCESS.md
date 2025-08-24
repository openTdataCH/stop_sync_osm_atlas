## Matching Process (Second Edition)

The matcher is sequential and “hit-first”: once an ATLAS row matches, it is removed from later stages. It targets platform-level granularity and avoids station-level OSM nodes.

- **Entrypoint**: `final_pipeline()` in [matching_process/matching_script.py](../matching_process/matching_script.py)
- **Input filters**: Only ATLAS `BOARDING_PLATFORM`; OSM stations are excluded via `utils.is_osm_station`
- **Uniqueness guard**: A used-OSM-node set prevents unintended reuse across stages

Stages (in order):
1. `exact_matching()` — UIC (`number` ↔ `uic_ref`), disambiguate with `designation` ↔ `local_ref`
2. `name_based_matching()` — `designationOfficial` ↔ `name`/`uic_name`/`gtfs:name`, `local_ref` tie-breaker
3. `distance_matching()` — group proximity, exact `local_ref` ≤ 50 m, proximity 3a/3b, plus isolation tagging
4. `perform_unified_route_matching()` — unified GTFS/HRDF tokens within 50 m
5. Post-pass unique-by-UIC consolidation (safe exact)
6. Duplicate propagation across ATLAS duplicates (`number` + `designation`)
7. Apply persistent manual matches from DB

## Exact and Name Matching

This Section outlines the logic of the `exact_matching` and `name_based_matching` stages from `matching_script.py`. These stages run sequentially and filter out OSM nodes tagged as stations (`railway=station` or `public_transport=station`) to avoid matching individual stops to entire station complexes.

---

### Exact Matching (`exact_matching` in [matching_process/exact_matching.py](../matching_process/exact_matching.py))

This is the first and highest-confidence matching stage. It aims to match ATLAS entries to OSM nodes using their shared UIC reference number.

Logic

The process groups ATLAS entries by their `number` (UIC reference) and attempts to match them against OSM nodes with the same `uic_ref`.

1.  Single OSM candidate (many-to-one): one OSM node → all ATLAS entries of that UIC
2.  Single ATLAS candidate (one-to-many): one ATLAS entry → all OSM nodes of that UIC
3.  Multiple candidates: require `designation` == `local_ref` (case-insensitive) for one-to-one pairing

ATLAS entries that do not fall into one of these cases are passed to the next stage.

---

### Name-Based Matching (`name_based_matching` in [matching_process/name_matching.py](../matching_process/name_matching.py))

This stage attempts to match the remaining ATLAS entries by comparing official names.

Logic

The process iterates through each unmatched ATLAS entry.

1. Use `designationOfficial` to look up OSM `name`/`uic_name`/`gtfs:name`
2. If multiple candidates, disambiguate by `designation` == `local_ref` (case-insensitive)

If no single candidate can be identified, the ATLAS entry remains unmatched and is passed to the next matching stage.

---

### Notes

- Exact matching permits many-to-one and one-to-many when safe, while later stages enforce one-to-one with distance constraints
- `designation` vs. `designationOfficial` play distinct roles (tie-breaker vs. lookup)
- Station-level OSM nodes are excluded to keep platform-level granularity

## Distance Matching (`distance_matching` in [matching_process/distance_matching.py](../matching_process/distance_matching.py))

This section outlines the logic of the different distance matching stages implemented in `distance_matching.py`. The process is sequential, and each stage attempts to match ATLAS entries that were not successfully matched in the preceding stages.

A critical feature of this process is the use of a `used_osm_node_ids` set, which ensures that once an OSM node is matched, it cannot be matched again to another ATLAS entry, thus preventing problematic many-to-one relationships.

---

### Stage 1: Group-based proximity (`distance_matching_1_*`)

This initial stage operates on groups of ATLAS entries and OSM nodes that share a common identifier.

- Grouping identifiers (in order): UIC (`number`/`uic_ref`), `uic_name`, `name` (using `designationOfficial`)

- Conditions: equal counts, reciprocal closest-pair mapping, and all pairs within 50 m
- Fallback: retry using only `public_transport=stop_position` nodes

---

### Stage 2: Exact `local_ref` (`distance_matching_2`)

This stage attempts to find a one-to-one match by using the ATLAS `designation` field as a precise key to find an OSM node with a matching `local_ref`.

- One-to-one if `local_ref` equals ATLAS `designation` within 50 m (closest wins)

---

### Stage 3: Proximity (`distance_matching_3a`, `distance_matching_3b`)

This stage makes matches based on proximity when a direct identifier match is not possible. It is divided into two distinct cases:

- 3a: exactly one candidate within 50 m
- 3b: multiple candidates; accept closest if `d2 >= 10 m` and `d2/d1 >= 4`

---

### Stage 4: No nearby OSM (`no_nearby_counterpart`)

This final stage does not create matches but instead identifies ATLAS entries for which no corresponding OSM data is likely to exist.

- Flags ATLAS entries with no OSM nodes within the isolation radius (50 m)

---


## Route-based Matching (Unified GTFS/HRDF)

`perform_unified_route_matching()` in [matching_process/route_matching_unified.py](../matching_process/route_matching_unified.py)

- Candidates: unused OSM nodes ≤ 50 m
- Uses per-sloid tokens from `data/processed/atlas_routes_unified.csv` and per-node tokens from `data/processed/osm_nodes_with_routes.csv`
- Also derives OSM direction strings from route relations in the OSM XML
- Priority: GTFS route_id(+normalized)+direction → HRDF line_name+direction_uic → direction-name fallback

## Post-processing

- Unique-by-UIC consolidation: if exactly one unused, non-station OSM node remains for a UIC, match it
- Duplicate propagation: propagate best match across ATLAS duplicates (`number` + `designation`)
- Manual matches: apply stored pairs from `PersistentData` (`problem_type='unmatched'`, `solution='manual'`)

## On our last run (headline numbers)

- ATLAS considered: 54,880 `BOARDING_PLATFORM`
- Matches (pairs): 48,213; distinct matched ATLAS: 46,611 (~85.0%)
- By method (pairs):
  - Exact: 21,124
  - Name: 535
  - Distance: 18,661
    - Stage 1 (group proximity): 15,384
    - Stage 2 (`local_ref` ≤ 50 m): 129
    - Stage 3a (single candidate): 2,012
    - Stage 3b (relative distance): 1,136
  - Routes (unified GTFS/HRDF): 6,944
  - Post-pass unique-by-UIC: 883
  - Duplicate propagation: 66
- Unmatched ATLAS: 8,269; of which 3,856 have no OSM within 50 m
- Unmatched OSM nodes: 19,107; of which 14,003 have ≥1 route, 14,906 have `uic_ref`, 876 have `local_ref`

## Key code references

- Orchestrator: `final_pipeline()` in [matching_process/matching_script.py](../matching_process/matching_script.py)
- Exact: `exact_matching()` in [matching_process/exact_matching.py](../matching_process/exact_matching.py)
- Name: `name_based_matching()` in [matching_process/name_matching.py](../matching_process/name_matching.py)
- Distance: `distance_matching()` and `transform_for_distance_matching()` in [matching_process/distance_matching.py](../matching_process/distance_matching.py)
- Routes: `perform_unified_route_matching()` in [matching_process/route_matching_unified.py](../matching_process/route_matching_unified.py)
- Utilities: `is_osm_station`, `haversine_distance` in [matching_process/utils.py](../matching_process/utils.py); KDTree helpers in [matching_process/spatial_index.py](../matching_process/spatial_index.py)

## Running the pipeline (summary)

- Ensure inputs exist or auto-download:
  - `ATLAS_STOPS_CSV` (default `data/raw/stops_ATLAS.csv`)
  - `OSM_XML_FILE` (default `data/raw/osm_data.xml`)
- Call `final_pipeline()` in [matching_process/matching_script.py](../matching_process/matching_script.py); it prints a summary and returns match datasets for DB import
