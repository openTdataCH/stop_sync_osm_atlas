## GTFS vs HRDF: Effectiveness, Coverage, and Compatibility

This document explains what the analysis script `memoire/scripts_used/gtfs_hrdf_effectiveness_analysis.py` does, why it does it, and how to interpret the results. It also highlights strengths and caveats of using GTFS and HRDF to match ATLAS stops to OSM nodes.

### What the script analyzes

The script computes four complementary views:

- Coverage: How much of the ATLAS universe each dataset (GTFS and HRDF) covers and how rich each sloid is in terms of available route/direction information.
- Internal compatibility: Whether GTFS and HRDF encode consistent direction strings at the sloid level (via Jaccard similarity of direction-name sets).
- Theoretical OSM compatibility:
  - GTFS: Based on `(route_id, direction_id)` keys shared with OSM route-tagged nodes.
  - HRDF: Based on shared direction strings (name and UIC) with OSM route relations and identical station UIC.
  The script measures how many sloids can find OSM candidates globally and within 50m, and provides distance summaries for those within the threshold.
- Actual matching effectiveness: Runs the in-repo orchestrator to perform matching with GTFS-only and HRDF-only strategies, reporting match counts, uniqueness, cardinality, and distance distributions, and whether both strategies ever disagree for the same sloid.

### Inputs used

- `data/raw/stops_ATLAS.csv` (from `get_atlas_data.py`)
- `data/raw/osm_data.xml` (from your OSM extractor)
- `data/processed/atlas_routes_gtfs.csv` (GTFS-derived route/direction per sloid, from `get_atlas_data.py`)
- `data/processed/atlas_routes_hrdf.csv` (HRDF-derived direction-name/UIC per sloid, from `get_atlas_data.py`)
- `data/processed/osm_nodes_with_routes.csv` (OSM nodes with GTFS route annotations)

It also reuses in-repo logic for:

- `matching_process.matching_script.parse_osm_xml` (robust OSM node parser with indexes)
- `matching_process.route_matching.route_matching` (orchestrator for actual matching)
- `matching_process.route_matching._get_osm_directions_from_xml` (extract OSM direction strings from route relations)
- `matching_process.utils.haversine_distance`

If some processed artifacts are missing, the script degrades gracefully and skips the corresponding sections while logging warnings.

### What the script produces

- A verbose console report summarizing key metrics.
- A machine-readable JSON file: `data/processed/gtfs_hrdf_effectiveness_summary.json` with all computed metrics.
- Optional figure `memoire/figures/plots/gtfs_hrdf_jaccard.png` (if `matplotlib` is available) showing the distribution of per-sloid Jaccard similarity of direction-name sets (GTFS vs HRDF).

### Methodological details

1) Coverage

- Counts unique sloids present in `atlas_routes_gtfs.csv` and `atlas_routes_hrdf.csv` and their fractions over all ATLAS sloids.
- Summarizes per-sloid richness:
  - GTFS: number of routes per sloid.
  - HRDF: number of direction-name entries per sloid.
- Computes overlap: sloids present in both GTFS and HRDF vs GTFS-only and HRDF-only.

2) Internal compatibility (GTFS vs HRDF)

- For each sloid present in both, the script compares the set of direction-name strings and computes the Jaccard index.
- It summarizes the distribution (min/median/p90/max/mean/std) and the share of sloids with:
  - Non-empty intersection (> 0)
  - Perfect match (= 1)

3) Theoretical OSM compatibility

- GTFS path:
  - Builds keys `(route_id, direction_id)` for each sloid from `atlas_routes_gtfs.csv`.
  - Builds the corresponding map of OSM nodes carrying those keys from `osm_nodes_with_routes.csv` (missing `direction_id` on OSM is expanded to both 0 and 1).
  - For each sloid, aggregates candidate OSM nodes globally, then filters to those within 50m of the sloid position (Haversine).
  - Greedy unique assignment chooses the nearest candidate not used yet and summarizes distances and cardinalities.

- HRDF path:
  - Extracts OSM direction strings per node from `osm_data.xml` relations of type `route` (both name-based and UIC-based origin→destination patterns) and indexes them by node.
  - For each sloid, identifies OSM nodes that share the same station UIC and at least one direction string (name or UIC).
  - Aggregates candidates globally and within 50m, then performs the same greedy unique assignment and summarizes distances and cardinalities.

4) Actual matching via orchestrator

- Runs `route_matching(..., strategy='gtfs')` and `route_matching(..., strategy='hrdf')` independently.
- Reports, for each strategy:
  - Total matches, unique sloids matched, unique OSM nodes used.
  - Match cardinality (one-to-one, one-to-many, many-to-one) among produced pairs.
  - Distance distribution for the matched pairs.
- Computes the overlap of sloids matched by both strategies and whether they picked different OSM nodes (conflict rate).

### Interpreting the results

- Coverage says whether GTFS and HRDF have enough information for a given sloid; higher coverage improves potential matching reach.
- Internal compatibility (Jaccard) quantifies whether direction-name vocabularies align; higher Jaccard suggests the datasets are coherent for route directions.
- Theoretical OSM compatibility is an upper bound under idealized rules:
  - For GTFS, it checks whether OSM has nodes annotated with the same `(route_id, direction_id)` and whether they are spatially plausible.
  - For HRDF, it checks whether direction strings and station UICs line up with OSM’s route relations and node tagging.
  - Distances and greedy assignment provide a sense of spatial quality and uniqueness pressure.
- Actual matching converts these potentials into real pairs using your production logic, thus integrating all heuristics and guardrails.

### Pros and cons of the approach

Pros

- Relies on reproducible artifacts from your existing pipeline (deterministic and consistent with the thesis codebase).
- Multi-perspective evaluation: coverage, internal coherence (Jaccard), theoretical OSM compatibility, and realized matches.
- Transparent, JSON-exported summary for downstream dashboards or paper tables.
- Distance summaries and cardinality metrics highlight spatial quality and many-to-one pressure points.

Cons / caveats

- Theoretical compatibility assumes correctness of OSM route annotations. Incomplete tagging will underestimate GTFS compatibility.
- Direction-name comparisons (Jaccard) are sensitive to naming conventions and diacritics; small differences lower the score while still being semantically aligned.
- Greedy assignment resolves collisions simply by nearest candidate; optimal global assignment is not attempted (e.g., Hungarian algorithm), trading optimality for interpretability and speed.
- HRDF’s direction derivation depends on correctly parsed HRDF files and on OSM relation structure; rail vs bus modes may differ in tagging practices.

### How to run

Make sure you have generated the prerequisite data:

```bash
python3 get_atlas_data.py
# And prepare your OSM XML extract at data/raw/osm_data.xml
```

Run the analysis:

```bash
python3 memoire/scripts_used/gtfs_hrdf_effectiveness_analysis.py
```

Outputs to check:

- Console summary
- `data/processed/gtfs_hrdf_effectiveness_summary.json`
- Optional figure `memoire/figures/plots/gtfs_hrdf_jaccard.png`

### Suggested questions to explore with this output

- Do GTFS and HRDF cover complementary sets of sloids? If yes, is a combined strategy warranted by coverage alone?
- Are distance distributions similar between GTFS-only and HRDF-only matches? Which is more precise spatially (lower median/p90 distances)?
- Are conflicts frequent where both match the same sloid? Investigate outliers to refine logic.
- Where Jaccard is low but both match successfully, what naming divergences exist between GTFS and HRDF?
- For sloids with many-to-one OSM pressure, would stronger disambiguation rules (e.g., operator consistency, stop type) reduce ambiguity?


