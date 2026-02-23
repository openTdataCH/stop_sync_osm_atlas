# Testing the Full Pipeline with a Minimal Dataset

Running the full matching pipeline (OSM XML parsing, KD-Tree construction, multiple predicate passes, routing analysis, and problem detection) takes significant time on the full 60,000+ stop dataset. 

To iterate quickly when refactoring core architecture (like pipeline state or problem thresholds), we need a **representative micro-dataset** of ~40 stops that triggers every edge case in the codebase.

## 1. The Strategy

We will extract a small bounding box or a hand-picked subset of stops from the database that deliberately includes:
1. **Clean Exact Matches** (1:1 ATLAS to OSM by UIC).
2. **Many-to-Many Conflicts** (Multiple ATLAS stops holding the same UIC attempting to map to multiple OSM nodes, requiring `local_ref` disambiguation).
3. **Name Matches** (No UIC, matching by `designationOfficial`).
4. **Distance Fallbacks** (Group proximity and ratio testing).
5. **Route Matches** (Stops exclusively matchable via GTFS/HRDF tokens).
6. **Duplicate Groups** (Multiple SLOIDs marked as duplicates where only one maps, triggering `duplicate_propagation`).
7. **Isolation / Problems** (Stops intentionally stranded >200m from anything, triggering `isolation` detection and `distance` anomalies).

By passing these 40 ATLAS records and their corresponding OSM nodes into the exact same `final_pipeline()` function from `matching_script.py`, we can run the *entire* pipeline end-to-end in `< 1.0 seconds`.

## 2. Generating the Micro-Dataset

Since we want to preserve the exact data structures the pipeline expects, we should save these subsets as static files in a `tests/data/` folder.

### ATLAS Data (`tests/data/sample_atlas.csv`)
Run this query to extract the 40 diverse stops and export the result to CSV:

```sql
-- Query to capture a diverse cross-section of match types and edge cases
(SELECT * FROM stops WHERE match_type = 'exact' LIMIT 5)
UNION ALL
(SELECT * FROM stops WHERE match_type = 'exact' AND uic_ref IS NOT NULL AND local_ref IS NOT NULL LIMIT 3) -- Disambiguation
UNION ALL
(SELECT * FROM stops WHERE match_type = 'name' LIMIT 5)
UNION ALL
(SELECT * FROM stops WHERE match_type LIKE 'distance%' LIMIT 10)
UNION ALL
(SELECT * FROM stops WHERE match_type = 'route_match' LIMIT 5)
UNION ALL
(SELECT * FROM stops WHERE match_type = 'duplicate_propagation' LIMIT 5)
UNION ALL
(SELECT * FROM stops WHERE match_type = 'manual' LIMIT 2)
UNION ALL
(SELECT * FROM stops WHERE problem_distance IS TRUE OR problem_isolation IS TRUE LIMIT 5);
```
*Export the results of this query to `tests/data/sample_atlas.csv`.*

### OSM Data (`tests/data/sample_osm.xml`)
To get the OSM nodes corresponding to these stops (plus some surrounding noise to test KDTree logic), we can use the `wgs84East` / `wgs84North` bounds of the selected ATLAS stops and download a small bounding box directly from the Overpass API, or simply filter the existing `osm_public_transport.xml`.

Alternatively, if you know a specific Swiss town (e.g., a complex station like "Arth-Goldau" or "Olten") that encompasses all these edge cases in one place, you can simply crop the `atlas_stops.csv` to that bounding box and use Overpass to pull the XML:
```text
[out:xml][timeout:25];
(
  node["public_transport"](<bbox>);
  node["railway"="station"](<bbox>);
  node["railway"="halt"](<bbox>);
  node["aerialway"="station"](<bbox>);
);
out body;
```

### Route Data (`tests/data/sample_routes.csv`)
If testing route matching, extract the GTFS/HRDF rows corresponding specifically to the SLOIDs captured in the step above.

## 3. The Test Script: `tests/test_full_pipeline.py`

Once the static files are saved, you can create a test script that hooks directly into the production pipeline using dependency injection for the file paths.

```python
import pandas as pd
from matching_process.matching_script import final_pipeline, identify_sloid_groups
from matching_process.osm_parser import parse_osm_xml
from matching_process.pipeline import MatchingContext, DEFAULT_PIPELINE
from matching_process.state import AtlasState, OsmIndex

def test_micro_pipeline_execution():
    """Run the entire matching pipeline on a representative 40-stop dataset."""
    
    # 1. Load the micro-datasets
    atlas_df = pd.read_csv("tests/data/sample_atlas.csv")
    osm_nodes = parse_osm_xml("tests/data/sample_osm.xml")
    
    # 2. Build the indices just like in matching_script.py
    uic_ref_dict = ... # (build from osm_nodes)
    name_index = ...   # (build from osm_nodes)
    
    atlas_state = AtlasState(
        atlas_df=atlas_df,
        duplicate_sloid_map=identify_sloid_groups(atlas_df)
    )
    osm_index = OsmIndex(
        xml_nodes=osm_nodes,
        uic_ref_dict=uic_ref_dict,
        name_index=name_index
    )
    
    ctx = MatchingContext(
        atlas=atlas_state,
        osm=osm_index,
        max_distance=50.0,
        osm_xml_file="tests/data/sample_osm.xml",
    )
    
    # 3. Execute!
    # Because there are only 40 records, this will take milliseconds.
    output = run_pipeline(DEFAULT_PIPELINE, ctx)
    
    # 4. Assertions ensuring pipeline features work correctly
    assert len(output.matched) > 0, "Pipeline failed to match any nodes."
    
    # Verify State Extraction worked
    assert len(ctx.osm.used_ids) == len(output.matched), "OSM used IDs out of sync."
    assert len(ctx.atlas.matched_ids) == len(output.matched), "ATLAS matched IDs out of sync."
    
    # Count match types to ensure predicates fired
    match_types = {m['match_type'] for m in output.matched}
    assert 'exact' in match_types
    assert 'name' in match_types
    # ... etc
```

### Benefits of this approach
1. **Speed**: Run `pytest tests/test_full_pipeline.py` incessantly while developing.
2. **Consistency**: Hardcoded CSV/XML files mean if a refactor breaks route matching, it fails deterministically without depending on external databases or network calls.
3. **No Mocks**: Because the pipeline functions natively accept `pandas.DataFrame` and `xml` paths, we don't need complex `unittest.mock` patching—we just feed it smaller real files.
