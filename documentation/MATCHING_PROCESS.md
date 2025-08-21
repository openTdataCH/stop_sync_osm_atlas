## Exact and Name Matching Logic

This Section outlines the logic of the `exact_matching` and `name_based_matching` stages from `matching_script.py`. These stages run sequentially and filter out OSM nodes tagged as stations (`railway=station` or `public_transport=station`) to avoid matching individual stops to entire station complexes.

---

### Exact Matching (`exact_matching`)

This is the first and highest-confidence matching stage. It aims to match ATLAS entries to OSM nodes using their shared UIC reference number.

**Logic Breakdown:**

The process groups ATLAS entries by their `number` (UIC reference) and attempts to match them against OSM nodes with the same `uic_ref`.

1.  **Single OSM Candidate (Many-to-One):** If there is only one available OSM node for a given UIC reference, all ATLAS entries with that same UIC reference are matched to that single OSM node.

2.  **Single ATLAS Candidate (One-to-Many):** If there is only one ATLAS entry for a given UIC reference, it is matched to all available OSM nodes that share that same UIC reference.

3.  **Multiple Candidates (One-to-One Disambiguation):** If there are multiple ATLAS entries and multiple OSM nodes for the same UIC reference, the algorithm attempts to find precise one-to-one matches. A match is made only if an ATLAS entry's `designation` (e.g., "Platform 7") is an exact, case-insensitive match for an OSM node's `local_ref` tag. Once an ATLAS entry or OSM node is matched this way, it cannot be matched again within the group.

ATLAS entries that do not fall into one of these cases are passed to the next stage.

---

### Name-Based Matching (`name_based_matching`)

This stage attempts to match the remaining ATLAS entries by comparing official names.

**Logic Breakdown:**

The process iterates through each unmatched ATLAS entry.

1.  **Primary Lookup:** It uses the ATLAS entry's `designationOfficial` field as a key to search for OSM nodes that have a matching `name`, `uic_name`, or `gtfs:name`.

2.  **Match Resolution:**
    *   **Single Candidate:** If the search returns exactly one OSM candidate, a match is created.
    *   **Multiple Candidates (Disambiguation):** If the search returns multiple OSM candidates, the algorithm attempts to disambiguate. It looks for the specific candidate whose `local_ref` tag is an exact, case-insensitive match for the ATLAS entry's `designation` field. If a single clear winner is found, a match is made.

If no single candidate can be identified, the ATLAS entry remains unmatched and is passed to the next matching stage.

---

### Potential Inconsistencies & Key Observations

1.  **Permissive Mappings in Exact Matching:** The `exact_matching` logic explicitly allows for many-to-one and one-to-many mappings in certain scenarios. While this can be a valid approach for grouping all elements of a single real-world stop, it contrasts with the stricter one-to-one logic in other parts of the matching process.

2.  **`designation` vs. `designationOfficial`:** The two stages use different fields for their primary logic. `exact_matching` uses `designation` for disambiguation, while `name_based_matching` uses `designationOfficial` for the initial search and `designation` for disambiguation. This separation is logical but highlights the importance of both fields being accurate in the source data.

3.  **Exclusion of Stations:** Both processes explicitly filter out and ignore OSM nodes that are tagged as larger stations. This is a critical design choice to ensure that granular stops (like individual bus stops or platforms) are not incorrectly matched to an entire train station complex. 

## Distance Matching Logic

This section outlines the logic of the different distance matching stages implemented in `distance_matching.py`. The process is sequential, and each stage attempts to match ATLAS entries that were not successfully matched in the preceding stages.

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

### Stage 4: No Nearby OSM Node (`no_nearby_counterpart`)

This final stage does not create matches but instead identifies ATLAS entries for which no corresponding OSM data is likely to exist.

- **Logic**: It flags any remaining unmatched ATLAS entries that have no OSM nodes within the configured isolation radius (50 meters by default).
- **Purpose**: This is crucial for data quality analysis, as it highlights areas where the ATLAS dataset has coverage but OpenStreetMap does not.

---
