## Problem Detection and Prioritization

This defines how problems are detected and prioritized. Core logic lives in [matching_process/problem_detection.py](../matching_process/problem_detection.py). Problems are stored in `problems` with `priority` (1 = highest). Each problem has at most one `solution` and an `is_persistent` flag.

Problem types: distance, unmatched, attributes, duplicates

Schema note: `problems.priority` (TINYINT), indexed.

Key functions (links to file):
- `analyze_stop_problems()` → aggregator
- `compute_distance_priority()` / `detect_distance_problems()`
- `compute_attributes_priority()` / `detect_attribute_problems()`
- `detect_atlas_isolation()` / `detect_osm_isolation()`

### 1) Distance

- Purpose: matched ATLAS–OSM pairs too far apart
- Detection: `detect_distance_problems()` uses `compute_distance_priority()`; problem exists if priority != NULL
- Applied: during DB import in [import_data_db.py](../import_data_db.py)

Priorities
- P1: ATLAS operator != SBB and distance > 80 m
- P2: ATLAS operator != SBB and 25 < distance ≤ 80 m
- P3: ATLAS operator == SBB and distance > 25 m, or any operator with 15 < distance ≤ 25 m
- None: distance ≤ 15 m or missing

### 2) Unmatched

- Purpose: stops without a counterpart
- Detection:
  - Batch isolation: `detect_atlas_isolation()` / `detect_osm_isolation()` (KDTree)
  - Single-entry flag: `detect_unmatched_problems(stop_type, match_type, is_isolated)`
  - Applied during matching (Stage 4) and finalized at import

Efficient priorities (computed in [import_data_db.py](../import_data_db.py))
- Build KDTree(s) once per run; compute nearest distances in meters
- Precompute counts by UIC: `atlas_count_by_uic`, `osm_count_by_uic`, `osm_platform_count_by_uic` (platform-like = `platform` or `stop_position`)

Priorities
- P1: zero opposite UIC; or ATLAS has no OSM within 80 m
- P2: no opposite within 50 m; or platform counts mismatch for the UIC
- P3: remaining unmatched

### 3) Attributes

- Purpose: inconsistent descriptive data for matched pairs
- Detection: `detect_attribute_problems()`; priority via `compute_attributes_priority()`

Priorities
- P1: different UIC or different official name
- P2: different local_ref
- P3: different operator

Operator normalization: see [OPERATOR_NORMALIZATION.md](./OPERATOR_NORMALIZATION.md) (OSM operators normalized before comparisons).

### 4) Duplicates

- Purpose: duplicated entries on ATLAS or OSM sides
- Detection:
  - ATLAS duplicates: use `duplicate_sloid_map` from the matching pipeline
  - OSM duplicates: multiple platform-like nodes (same `uic_ref`, same `local_ref`)

Priorities
- P2: ATLAS duplicates
- P3: OSM duplicates

Implementation (in [import_data_db.py](../import_data_db.py))
- ATLAS: if `sloid` is in `duplicate_sloid_map` → create `duplicates` problem (P2)
- OSM: if node in duplicate set for `(uic_ref, local_ref)` among platform-like nodes → `duplicates` (P3)
- API groups duplicates in `/api/problems` for UI review (see [backend/blueprints/problems.py](../backend/blueprints/problems.py))

### Data flow
1) Matching pipeline produces `base_data`
2) Import writes `stops`, `atlas_stops`, `osm_nodes`, and creates `problems` with priorities
3) Persistent solutions are applied post-import

### Notes
- `PersistentData.note` captures reviewer context; applied on import (see [PERSISTENT_DATA.md](./PERSISTENT_DATA.md))

### Configuration
- Flags in [matching_process/problem_detection.py](../matching_process/problem_detection.py): `ENABLE_OPERATOR_MISMATCH_CHECK`, `ENABLE_NAME_MISMATCH_CHECK`, `ENABLE_UIC_MISMATCH_CHECK`, `ENABLE_LOCAL_REF_MISMATCH_CHECK`
- Isolation radius: 50 m via `get_isolation_radius()`

 