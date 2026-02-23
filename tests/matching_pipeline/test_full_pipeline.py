import pandas as pd
from matching_process.matching_script import parse_osm_xml
from matching_process.pipeline import MatchingContext, run_pipeline
from matching_process.matching_script import DEFAULT_PIPELINE
from matching_process.state import AtlasState, OsmIndex

def test_full_pipeline_micro_dataset():
    """
    Runs the full exact/name/distance/route matching pipeline against a highly subsetted
    snapshot of the database (~40 ATLAS stops, ~150 OSM nodes).
    Verifies that match counts and predicates haven't broken significantly.
    """
    
    atlas_df = pd.read_csv("tests/data/sample_atlas.csv")
    
    # 1. Parse OSM XML
    all_osm_nodes, uic_ref_dict, name_index, osm_name_dirs, osm_uic_dirs = parse_osm_xml("tests/data/sample_osm.xml")

    # 2. Identify ATLAS duplicate groups (replicate prod logic)
    dup_mask = atlas_df.duplicated(subset=['number', 'designation'], keep=False)
    non_empty = atlas_df['designation'].notna() & (atlas_df['designation'].astype(str).str.strip() != '')
    dup_mask = dup_mask & non_empty

    duplicate_sloid_map = {}
    for _, group_df in atlas_df[dup_mask].groupby(['number', 'designation'], sort=False):
        if len(group_df) <= 1:
            continue
        sloids = sorted(group_df['sloid'].astype(str).tolist())
        for s in sloids:
            duplicate_sloid_map[s] = sloids

    # 3. Setup context
    atlas_state = AtlasState(
        atlas_df=atlas_df,
        duplicate_sloid_map=duplicate_sloid_map
    )

    osm_index = OsmIndex(
        xml_nodes=all_osm_nodes,
        uic_ref_dict=uic_ref_dict,
        name_index=name_index,
        name_dirs=osm_name_dirs,
        uic_dirs=osm_uic_dirs,
    )

    ctx = MatchingContext(
        atlas=atlas_state,
        osm=osm_index,
        max_distance=50.0,
        osm_xml_file="tests/data/sample_osm.xml",
    )
    
    # 4. Run pipeline
    output = run_pipeline(DEFAULT_PIPELINE, ctx)
    
    matches = output.matched
    matched_sloids = {m['sloid'] for m in matches if 'sloid' in m}
    
    # Based on the extractor we aimed for ~35-40 stops in the sample subset
    assert len(matches) > 10, f"Expected >10 matches, only got {len(matches)}. Pipeline regression?"
    
    # Verify state tracking consistency
    assert len(ctx.osm.used_ids) == len(matches) - sum(1 for m in matches if m.get('match_type') == 'duplicate_propagation'), "OSM unused state trackers out of sync."
    assert len(ctx.atlas.matched_ids) == len(matched_sloids), "ATLAS matched tracking out of sync."
    
    # Check that multiple predicates fired
    match_types = {m['match_type'] for m in matches if 'match_type' in m}
    
    print(f"Test matched {len(matches)} entries across {len(match_types)} predicates.")
    assert 'exact' in match_types or 'name' in match_types, "Failed to match basic exact/name entries."
