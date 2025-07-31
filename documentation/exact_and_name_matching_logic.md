# Exact and Name Matching Logic

This document outlines the logic of the `exact_matching` and `name_based_matching` stages from `matching_script.py`. These stages run sequentially and filter out OSM nodes tagged as stations (`railway=station` or `public_transport=station`) to avoid matching individual stops to entire station complexes.

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