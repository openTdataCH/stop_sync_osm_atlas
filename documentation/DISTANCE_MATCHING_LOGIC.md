# Distance Matching Logic

This document outlines the logic of the different distance matching stages implemented in `distance_matching.py`. The process is sequential, and each stage attempts to match ATLAS entries that were not successfully matched in the preceding stages.

A critical feature of this process is the use of a `used_osm_node_ids` set, which ensures that once an OSM node is matched, it cannot be matched again to another ATLAS entry, thus preventing problematic many-to-one relationships.

---

### Stage 1: Group-Based Proximity Matching (`distance_matching_1_*`)

This initial stage operates on groups of ATLAS entries and OSM nodes that share a common identifier.

- **Grouping Identifiers**: The matching is attempted sequentially based on the following shared properties:
    1.  `UIC reference` (ATLAS `number` and OSM `uic_ref`)
    2.  `uic_name` (ATLAS `designationOfficial` and OSM `uic_name`)
    3.  `name` (ATLAS `designationOfficial` and OSM `name`)

- **Matching Condition**: A match is attempted only if the number of unmatched ATLAS entries for a given identifier is exactly equal to the number of available (unmatched) OSM nodes for that same identifier.

- **Conflict-Free Assignment**: When the counts are equal, the algorithm performs a conflict-free proximity assignment. This means each ATLAS entry is matched to its closest OSM node, and crucially, each OSM node is also matched to its closest ATLAS entry. If this reciprocal relationship holds true for all members of the group, the matches are confirmed.

- **Distance Constraint**: For a group match to be valid, **all** resulting pairs must be within the defined maximum distance (e.g., 50 meters). If even one pair exceeds this distance, the entire group match is discarded, and the entries are passed to subsequent matching stages.

- **Fallback to `stop_position`**: If the initial group match fails, the algorithm makes a second attempt using only the OSM nodes in the group that are tagged with `public_transport=stop_position`. The logic remains the same.

---

### Stage 2: Exact `local_ref` Matching (`distance_matching_2`)

This stage attempts to find a one-to-one match by using the ATLAS `designation` field as a precise key to find an OSM node with a matching `local_ref`.

- **Logic**: For a given ATLAS entry, the algorithm searches for an OSM node located within a defined maximum distance (e.g., 50 meters).
- **Condition**: A match is made if the OSM node has a `local_ref` tag that is an exact (case-insensitive) match to the ATLAS entry's `designation`. If multiple OSM nodes meet this criterion, the closest one is chosen.

---

### Stage 3: Proximity-Based Matching (`distance_matching_3a` and `distance_matching_3b`)

This stage makes matches based on proximity when a direct identifier match is not possible. It is divided into two distinct cases:

- **Stage 3a (Single Candidate)**:
    - **Condition**: A match is created if there is exactly one OSM node candidate within the maximum search distance of an ATLAS entry.

- **Stage 3b (Relative Distance Disambiguation)**:
    - **Condition**: This applies when there are multiple OSM candidates. A match is made with the closest candidate (at distance `d1`) only if it is significantly more likely to be the correct match than the second-closest candidate (at distance `d2`).
    - **Rules**:
        1. The second-closest node must be at least 10 meters away (`d2 >= 10`).
        2. The closest node must be at least four times closer than the second-closest node (`d2 / d1 >= 4`).

---

### Stage 4: No Nearby OSM Node (`no_osm_within_50m`)

This final stage does not create matches but instead identifies ATLAS entries for which no corresponding OSM data is likely to exist.

- **Logic**: It flags any remaining unmatched ATLAS entries that have no OSM nodes within a 50-meter radius.
- **Purpose**: This is crucial for data quality analysis, as it highlights areas where the ATLAS dataset has coverage but OpenStreetMap does not.

---
