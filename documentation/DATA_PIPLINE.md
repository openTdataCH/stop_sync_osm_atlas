## Data Pipeline (End-to-End)

This document explains the full data pipeline, from input acquisition to database import. It links to the code and complements the matching and problem-detection docs.

### Overview

- **Inputs**
  - ATLAS stops CSV (Switzerland-only) produced by `get_atlas_data.py`
  - OSM public transport nodes and route relations XML produced by `get_osm_data.py`
- **Core processing**
  - Matching (ATLAS ↔ OSM) orchestrated by `final_pipeline()`
- **Outputs**
  - In-memory `base_data` (matched, unmatched_atlas, unmatched_osm)
  - Import into DB tables with automatic problem detection and route/direction consolidation

### 1) Data acquisition

- **ATLAS + GTFS + HRDF preparation**: `get_atlas_data.py`
  - File: [get_atlas_data.py](../get_atlas_data.py)
  - Produces:
    - `data/raw/stops_ATLAS.csv` (Swiss ATLAS stops; filtered precisely by CH polygon)
    - `data/processed/atlas_routes_unified.csv` via `write_unified_routes_csv_direct()`
      - Combines GTFS and HRDF into a single per-sloid set of tokens with provenance
  - Key functions:
    - `filter_points_in_switzerland()` (precise polygon filter)
    - `load_gtfs_data_streaming()` and `build_integrated_gtfs_data_streaming()` (memory-lean GTFS integration)
    - `process_hrdf_direction_data()` (HRDF directions from GLEISE/FPLAN)
    - `write_unified_routes_csv_direct()` (unified route file)

- **OSM + route extraction**: `get_osm_data.py`
  - File: [get_osm_data.py](../get_osm_data.py)
  - Produces:
    - `data/raw/osm_data.xml` (Overpass result)
    - `data/processed/osm_nodes_with_routes.csv` via `process_osm_data_to_csv()` (one row per node–route pair, with parsed direction_id)
  - Key functions:
    - `query_overpass()` (Switzerland public transport nodes and routes)
    - `process_osm_data_to_csv()` (node–route rows + `create_routes_with_nodes_csv()`)

### 2) Matching

- Orchestrator: `final_pipeline()` in [matching_process/matching_script.py](../matching_process/matching_script.py)
  - Loads inputs (with environment overrides) and calls the staged matchers:
    - `exact_matching()` in [matching_process/exact_matching.py](../matching_process/exact_matching.py)
    - `name_based_matching()` in [matching_process/name_matching.py](../matching_process/name_matching.py)
    - `distance_matching()` in [matching_process/distance_matching.py](../matching_process/distance_matching.py)
    - `perform_unified_route_matching()` in [matching_process/route_matching_unified.py](../matching_process/route_matching_unified.py)
  - Post-processing inside `final_pipeline()`:
    - Unique-by-UIC consolidation, duplicate propagation, persistent manual matches
    - Isolation marking for remaining unmatched OSM nodes via `detect_osm_isolation()`
  - Output: `(base_data, duplicate_sloid_map, no_nearby_osm_sloids)` where `base_data` contains:
    - `matched`: list of match records with rich fields
    - `unmatched_atlas`: remaining ATLAS rows
    - `unmatched_osm`: remaining OSM nodes annotated with isolation status

For the detailed stage-by-stage logic and recent run numbers, see [MATCHING_PROCESS.md](./MATCHING_PROCESS.md).

### 3) Database import and problem detection

- Import: `import_to_database()` in [import_data_db.py](../import_data_db.py)
  - Writes:
    - `stops` (core rows for matched, unmatched ATLAS, and unmatched OSM)
    - `atlas_stops` (descriptive ATLAS-side details, including `routes_unified` JSON)
    - `osm_nodes` (descriptive OSM-side details, including per-node routes)
    - `routes_and_directions` (consolidated per-route/direction groupings)
  - Loads and builds route mappings using:
    - `load_route_data()`, `load_unified_route_data()`, `build_route_direction_mapping()`
  - Detects and prioritizes problems using [matching_process/problem_detection.py](../matching_process/problem_detection.py):
    - `analyze_stop_problems()` orchestrates checks
    - `compute_distance_priority()`, `compute_attributes_priority()`
    - `detect_osm_isolation()` (used earlier and/or at import)
  - Applies persistent solutions/notes post-import via `apply_persistent_solutions()`

See also:
- Problem logic and priorities: [PROBLEM_DETECTION.md](./PROBLEM_DETECTION.md)
- Persistent solutions and notes: [PERSISTENT_DATA.md](./PERSISTENT_DATA.md)
- Unified route pipeline: [UNIFIED_ROUTE_PIPELINE.md](./UNIFIED_ROUTE_PIPELINE.md)

### 4) Operator normalization

- Purpose: make OSM `operator` comparable to ATLAS abbreviations
- Applied at XML parse time in `parse_osm_xml()` via `standardize_operator()`
- Code: [matching_process/org_standardization.py](../matching_process/org_standardization.py)
- Details: [OPERATOR_NORMALIZATION.md](./OPERATOR_NORMALIZATION.md)

### Running end-to-end

1. Generate inputs
   - `python get_atlas_data.py`
   - `python get_osm_data.py`
2. Run matching and import
   - `python import_data_db.py`

Environment overrides (optional):
- `ATLAS_STOPS_CSV` (default `data/raw/stops_ATLAS.csv`)
- `OSM_XML_FILE` (default `data/raw/osm_data.xml`)

On our last run, these were the headline numbers; see the breakdown in [MATCHING_PROCESS.md](./MATCHING_PROCESS.md).


