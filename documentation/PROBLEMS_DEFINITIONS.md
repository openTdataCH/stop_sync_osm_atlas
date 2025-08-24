## Problem Detection and Prioritization

This defines how problems are detected and prioritized. Core logic lives in [matching_process/problem_detection.py](../matching_process/problem_detection.py). Problems are stored in the table `problems` with `priority` (1 = highest). Each problem has at most one `solution` and an `is_persistent` flag.

Problem types: distance, unmatched, attributes, duplicates

### Problems Table Structure

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `stop_id` | Integer | Foreign key to `stops` table |
| `problem_type` | String | Type of problem: `distance`, `unmatched`, `attributes`, `duplicates` |
| `solution` | String | Human-readable solution description (optional) |
| `is_persistent` | Boolean | Whether solution persists across data imports |
| `priority` | Integer | Priority within problem type (1 = highest, 2 = medium, 3 = low) |
| `created_by_user_id` | Integer | ID of user who solved the problem (optional) |
| `created_by_user_email` | String | Email of user who solved the problem (optional) |

### 1) Distance

- Purpose: matched ATLAS–OSM pairs too far apart

Priorities
- P1: ATLAS operator != SBB and distance > 80 m
- P2: ATLAS operator != SBB and 25 < distance ≤ 80 m
- P3: ATLAS operator == SBB and distance > 25 m, or any operator with 15 < distance ≤ 25 m

- Detection: `detect_distance_problems()` uses `compute_distance_priority()`; problem exists if priority != NULL

### 2) Unmatched

- Purpose: stops without a counterpart

Priorities
- P1: zero opposite UIC; or ATLAS has no OSM within 80 m
- P2: no opposite within 50 m; or platform counts mismatch for the UIC
- P3: remaining unmatched

- Detection:
  - Batch isolation: `detect_atlas_isolation()` / `detect_osm_isolation()` (KDTree)
  - Single-entry flag: `detect_unmatched_problems(stop_type, match_type, is_isolated)`
  - Applied during matching (Stage 4) and finalized at import

### 3) Attributes

- Purpose: inconsistent descriptive data for matched pairs
- Detection: `detect_attribute_problems()`; priority via `compute_attributes_priority()`

Priorities
- P1: different UIC or different official name
- P2: different local_ref
- P3: different operator

Operator normalization: see [OPERATOR_NORMALIZATION.md](./OPERATOR_NORMALIZATION.md) (OSM operators normalized before comparisons).

### 4) Duplicates (work in peogress)

- Purpose: duplicated entries on ATLAS or OSM sides

Priorities
- P2: ATLAS duplicates
- P3: OSM duplicates

- Detection:
  - ATLAS duplicates: use `duplicate_sloid_map` from the matching pipeline
  - OSM duplicates: multiple platform-like nodes (same `uic_ref`, same `local_ref`)

Implementation (in [import_data_db.py](../import_data_db.py))
- ATLAS: if `sloid` is in `duplicate_sloid_map` → create `duplicates` problem (P2)
- OSM: if node in duplicate set for `(uic_ref, local_ref)` among platform-like nodes → `duplicates` (P3)
- API groups duplicates in `/api/problems` for UI review (see [backend/blueprints/problems.py](../backend/blueprints/problems.py))



 