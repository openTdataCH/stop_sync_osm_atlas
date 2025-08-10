## Problem Detection and Prioritization

This document precisely defines how we detect and prioritize problems. Logic lives in `matching_process/problem_detection.py`. Problems are stored in `problems` with a per-type `priority` (1 = highest).

Problem types:
- Distance
- Unmatched 
- Attributes
- Duplicates

We store a single `solution` per problem and a nullable `priority` (1, 2, 3). Non-problematic cases have `priority = NULL`.

Schema notes:
- Column `problems.priority` (TINYINT) and index `idx_problem_priority`
 

### 1. Distance

Purpose: matched ATLAS–OSM pairs too far apart.

Detection
- Function: `detect_distance_problems()` uses `compute_distance_priority()`; a problem exists if priority is not NULL.
- Applied: during database import in `import_data_db.py` when inserting `Stop` and `Problem` rows.

Priority rules
- Priority 1: ATLAS operator is not SBB AND distance > 80 m
- Priority 2: ATLAS operator is not SBB AND 25 m < distance ≤ 80 m
- Priority 3: ATLAS operator is SBB AND distance > 25 m; OR any operator with 15 m < distance ≤ 25 m
- Not a problem: distance ≤ 15 m or missing

Implementation
- Compute with `compute_distance_priority(record)` using `csv_business_org_abbr` and `distance_m` already present in match records (from matching stages).
- Store `Problem(priority=1|2|3)` when `detect_distance_problems(record)` returns True.

### 2. Unmatched

Purpose: stops without a counterpart in the opposite dataset.

Detection
- Spatial checks centralized in:
  - `detect_atlas_isolation()` and `detect_osm_isolation()` for batch KDTree checks.
  - `detect_unmatched_problems()` for single-entry checks (accepts `stop_type`, `match_type`, `is_isolated`).
- Applied: during distance matching Stage 4 and final pipeline, and finalized at import.

Efficient priority computation
- During import we build KDTree(s) once per run:
  - OSM KDTree from all OSM coordinates (both matched and unmatched) for ATLAS queries
  - ATLAS KDTree from all ATLAS coordinates for OSM queries
- We also precompute counts by UIC:
  - `atlas_count_by_uic` from matched + unmatched ATLAS
  - `osm_count_by_uic` and `osm_platform_count_by_uic` from matched OSM and `unmatched_osm.tags.public_transport in {platform, stop_position}`
- Distance queries convert 3D unit-vector distance back to great-circle meters.

Priority rules
- Priority 1:
  - 0 UIC-number stops in the opposite dataset (e.g., ATLAS UIC exists, OSM has none; or vice versa)
  - ATLAS with no OSM within 80 m
- Priority 2:
  - No opposite dataset entry within 50 m
  - Unequal number of platforms between OSM and ATLAS for the same UIC
    (Count OSM `public_transport` in {platform, stop_position} vs. count of ATLAS entries sharing that UIC)
- Priority 3: Remaining unmatched entries

Example (platform mismatch)
- ATLAS UIC 8500012 has 6 entries; OSM nodes with `uic_ref=8500012` have 5 nodes where `public_transport` ∈ {platform, stop_position} ⇒ unmatched priority 2.
- If OSM has 1 platform + 3 stop_positions (4 in total) and ATLAS has 6 entries ⇒ still a mismatch (priority 2).

Implementation
- ATLAS entries: `compute_unmatched_priority_for_atlas(rec)` combines nearest OSM search and UIC/platform counts.
- OSM entries: `compute_unmatched_priority_for_osm(rec)` combines nearest ATLAS search and UIC/platform counts.
- Problems are stored with `problem_type='unmatched'` and `priority` accordingly.
 

### 3. Attributes

Purpose: inconsistent descriptive data for matched pairs.

Detection
- Function: `detect_attribute_problems()` still generates details; `compute_attributes_priority()` assigns priority.

Priority rules
- Priority 1: Different UIC number OR different official name
- Priority 2: Different local_ref
- Priority 3: Different operator


### 4. Duplicates

Purpose: identify duplicated entries either on the ATLAS side or on the OSM side.

Detection
- ATLAS duplicates: We reuse the `duplicate_sloid_map` produced during the matching pipeline to mark entries that belong to a duplicate ATLAS group.
- OSM duplicates: We detect multiple OSM nodes that are platform-like and share the same UIC, the same local_ref, and the same public_transport type.
  - Platform-like means `public_transport` ∈ {platform, stop_position}.
  - Duplicates are detected per key (uic_ref, local_ref, public_transport) if there are two or more distinct node_ids for that key.
  - A `platform` and a `stop_position` with the same UIC and local_ref represent the same stop and are NOT considered duplicates.

Priority rules
- Priority 2: ATLAS duplicates
- Priority 3: OSM duplicates (two or more platform-like nodes with the same UIC, local_ref, and public_transport type)
  
Implementation
- In `import_data_db.import_to_database`:
  - For matched and unmatched ATLAS entries: if `sloid` is in `duplicate_sloid_map`, create `Problem(problem_type='duplicates', priority=2)`.
  - For matched and unmatched OSM entries: if the node_id is part of a duplicate set for its `(uic_ref, local_ref, public_transport)` among platform-like nodes, create `Problem(problem_type='duplicates', priority=3)`.
- No Priority 1 is defined for duplicates.

### Data flow summary
1) Matching pipeline produces `base_data` with rich fields.
2) Import (`import_data_db.import_to_database`) writes `stops`, `atlas_stops`, `osm_nodes`, and creates `problems` as needed with computed priorities.
3) Persistent solutions are applied post-import.


### Notes usage
- The `PersistentData.note` field is available to capture reviewer notes and can be used to annotate rationale behind manual resolutions.

### Configuration
Configuration defaults
- Attribute mismatch checks are enabled by default in `matching_process/problem_detection.py` via inline flags: `ENABLE_OPERATOR_MISMATCH_CHECK`, `ENABLE_NAME_MISMATCH_CHECK`, `ENABLE_UIC_MISMATCH_CHECK`, `ENABLE_LOCAL_REF_MISMATCH_CHECK`.
- Isolation radius defaults to 50 m via `get_isolation_radius()` inside `matching_process/problem_detection.py`.
- Distance classification uses the explicit priority rules above; import-level unmatched priorities use the 80 m and 50 m thresholds defined here.

 