# Route Matching Logic

This document describes the implementation (updated 2025-07-11) of `route_matching()` in `matching_process/route_matching.py`. The goal is to link every unmatched **ATLAS stop** to the correct **OSM node** by using *route* and *direction* information that both datasets share.

---

## 1  Data Preparation

Two pre-built CSV files are loaded at runtime:

| file | purpose |
|------|---------|
| `atlas_routes.csv` | maps an ATLAS `sloid` to one or more `(route_id, direction_id)` pairs |
| `osm_nodes_with_routes.csv` | maps an OSM `node_id` to one or more `(route_id, direction_id)` pairs |

### Normalisation applied while loading

* **SLOID** – always stored as a string (`"12345"`), preventing int/str mismatches.
* **Direction** – converted with
  ```python
  def _normalize_direction(v):
      return str(int(float(v)))   # 0, 0.0, "0" → "0" ; None/NaN → None
  ```
* **Missing direction** – if an OSM row has no usable value, two synthetic entries are created (direction "0" **and** "1") so the node can match either way.
* **Route-id fallback** – when `gtfs_route_id` is absent, the loader tries to look up the OSM `route_name` in the GTFS `routes.txt` file to find the corresponding `route_id` (by matching against `route_short_name` or `route_long_name`). If no match is found, the row is discarded.
* **Year code normalization** – route IDs are normalized by replacing year codes (j22, j24, j25, etc.) with a generic placeholder (jXX) to handle version mismatches between OSM and GTFS data. For example: `92-5-H-j24-1` becomes `92-5-H-jXX-1` for comparison purposes.

### Station filtering
`railway=station` and `public_transport=station` nodes are excluded **before** they reach the matcher, to keep the focus on stop_positions / platforms.

### Handling of Multi-Route Stops
The matching process iterates through every `(route, direction)` pair associated with an ATLAS stop. This ensures that stops serving multiple routes (e.g., a bus stop for Line 5 and Line 10) can be matched multiple times, once for each route. The algorithm does not stop after finding the first match for a given `sloid`.

---

## 2  Matching Stages

Both stages now use a **two-tier approach**: exact matching first, then normalized matching as fallback.

### Stage 1  Unique `(UIC ref, route, direction)`

**OSM Node Reuse Prevention**: Stage 1 tracks which OSM nodes have already been matched to prevent multiple ATLAS stops from matching to the same OSM node, ensuring true 1:1 relationships.

#### Exact Matching (Stage 1a)
1. Build keys on both sides: `(uic_ref, route_id, direction_id)`.
2. Keep a key **only** when it is *unique* in *both* datasets (exactly one OSM node **and** one ATLAS stop).
3. Check that the OSM node hasn't already been matched to another ATLAS stop.
4. If the coordinates are plausible, create a match with type `route_matching_1_exact`.
5. Mark the OSM node as used to prevent future matches.

#### Normalized Matching (Stage 1b) 
If exact matching fails:
1. Apply year code normalization to route IDs (j24→jXX, j25→jXX, etc.).
2. Build normalized keys: `(uic_ref, normalized_route_id, direction_id)`.
3. Apply same uniqueness criteria as exact matching.
4. Check that the OSM node hasn't already been matched to another ATLAS stop.
5. Create matches with type `route_matching_1_normalized`.
6. Mark the OSM node as used to prevent future matches.

This stage represents our highest-confidence links, with exact matches preferred over normalized ones.

### Stage 2  `(route, direction)` + proximity ≤ 50 m

**Many-to-Many Prevention**: Before performing Stage 2 matching, the system identifies which `(route, direction)` combinations are allowed to prevent incorrect many-to-many matches. For each combination, it counts the number of ATLAS stops and OSM nodes:

- **1 ATLAS : 1 OSM** → allowed (1:1 match)
- **1 ATLAS : multiple OSM** → allowed (1:many, picks closest)
- **multiple ATLAS : 1 OSM** → allowed (many:1, picks closest)
- **multiple ATLAS : multiple OSM** → **rejected** (many:many, could create incorrect matches)

#### Exact Matching (Stage 2a)
For every still-unmatched ATLAS stop:
1. Retrieve its list of `(route_id, direction_id)` pairs.
2. Check if the combination is allowed (not many-to-many).
3. Pull all OSM candidates that share one of those pairs (exact route ID match).
4. Compute the Haversine distance; choose the closest node if it is ≤ `max_distance` (default 50 m).
5. Create matches with type `route_matching_2_exact`.

#### Normalized Matching (Stage 2b)
If exact matching fails:
1. Apply year code normalization to route IDs.
2. Check if the normalized combination is allowed (not many-to-many).
3. Pull all OSM candidates that share normalized `(route_id, direction_id)` pairs.
4. Apply same distance criteria as exact matching.
5. Create matches with type `route_matching_2_normalized`.

When multiple candidates are within range only the nearest is accepted.

---

## 3  Additional Checks & Outputs

* **Operator mismatch** – if the OSM `operator` tag and the ATLAS business-organisation differ, the match is kept but the discrepancy is appended to `matching_notes` and logged in `data/debug/route_org_mismatches_review.txt`.
* **Logging & Statistics** – after execution the matcher prints a summary including:
  * number of tuples in each dataset
  * how many passed the uniqueness filter
  * matches per stage (broken down by exact vs normalized)
  * distance statistics
  * operator mismatch counts
* **Return value** – list of dictionaries, later stored in the `stops` table.

---

## 4  Dependencies & Failure Modes

| dependency | impact when missing / wrong |
|------------|-----------------------------|
| `atlas_routes.csv` | no routes for ATLAS ⇒ Stage 1 fails and Stage 2 has no pairs to compare |
| `osm_nodes_with_routes.csv` | no routes for OSM ⇒ both stages fail |
| GTFS `routes.txt` | used for route-id fallback; without it many OSM relations are discarded |
| Correct `uic_ref` tagging in OSM | needed only for Stage 1 |

If any of these inputs are poor the fallback (distance-only matching) has to cover the gaps.

---


