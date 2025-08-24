import os
import sys
import json
from pathlib import Path
import pandas as pd
import numpy as np

# Ensure project root is on sys.path to import matching_process
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from matching_process.matching_script import parse_osm_xml
from matching_process.exact_matching import exact_matching
from matching_process.route_matching_unified import perform_unified_route_matching


def ensure_dirs():
    out_dir = os.path.join('memoire', 'data', 'processed', 'chap4')
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def load_atlas_df():
    atlas_csv_file = os.path.join('data', 'raw', 'stops_ATLAS.csv')
    if not os.path.exists(atlas_csv_file):
        raise FileNotFoundError(f"ATLAS CSV not found: {atlas_csv_file}")
    df = pd.read_csv(atlas_csv_file, sep=';')
    return df


def analyze_route_matching_tokens():
    """Analyze the tokens available for route matching from both sides."""
    # Load unified routes data
    unified_path = os.path.join('data', 'processed', 'atlas_routes_unified.csv')
    unified_df = pd.read_csv(unified_path, dtype=str)
    
    # Load OSM routes data
    osm_routes_path = os.path.join('data', 'processed', 'osm_nodes_with_routes.csv')
    osm_routes_df = pd.read_csv(osm_routes_path, dtype=str)
    
    # Analyze GTFS tokens
    gtfs_data = unified_df[unified_df['source'] == 'gtfs'].copy()
    gtfs_tokens = set()
    for _, row in gtfs_data.iterrows():
        if pd.notna(row.get('route_id')) and pd.notna(row.get('direction_id')):
            gtfs_tokens.add((str(row['route_id']), str(row['direction_id'])))
        if pd.notna(row.get('route_id_normalized')) and pd.notna(row.get('direction_id')):
            gtfs_tokens.add((str(row['route_id_normalized']), str(row['direction_id'])))
    
    # Analyze OSM tokens
    osm_tokens = set()
    for _, row in osm_routes_df.iterrows():
        if pd.notna(row.get('gtfs_route_id')) and pd.notna(row.get('direction_id')):
            osm_tokens.add((str(row['gtfs_route_id']), str(row['direction_id'])))
    
    # Analyze HRDF tokens
    hrdf_data = unified_df[unified_df['source'] == 'hrdf'].copy()
    hrdf_uic_directions = set()
    for _, row in hrdf_data.iterrows():
        if pd.notna(row.get('direction_uic')):
            hrdf_uic_directions.add(str(row['direction_uic']))
    
    # Extract OSM UIC directions (simplified analysis)
    osm_uic_directions = set()
    # This would require parsing the OSM XML for route relations with UIC endpoints
    # For now, we'll use the data from route_matching_stats.py
    
    return {
        'gtfs_tokens_atlas': len(gtfs_tokens),
        'gtfs_tokens_osm': len(osm_tokens),
        'gtfs_token_overlap': len(gtfs_tokens & osm_tokens),
        'gtfs_jaccard': len(gtfs_tokens & osm_tokens) / len(gtfs_tokens | osm_tokens) if gtfs_tokens | osm_tokens else 0,
        'hrdf_uic_directions_atlas': len(hrdf_uic_directions),
        'atlas_sloids_with_gtfs': len(gtfs_data['sloid'].unique()),
        'atlas_sloids_with_hrdf': len(hrdf_data['sloid'].unique()),
        'osm_nodes_with_routes': len(osm_routes_df['node_id'].unique()),
    }


def analyze_route_matching_effectiveness():
    """Comprehensive analysis of route matching effectiveness."""
    out_dir = ensure_dirs()
    atlas_df = load_atlas_df()
    all_nodes, uic_ref_dict, _name_index = parse_osm_xml(os.path.join('data', 'raw', 'osm_data.xml'))
    
    print("=== ROUTE MATCHING EFFECTIVENESS ANALYSIS ===")
    
    # 1. Exact matching baseline
    print("1. Running exact matching (baseline)...")
    exact_matches, exact_unmatched, used_osm_exact = exact_matching(atlas_df, uic_ref_dict)
    exact_pairs = {(str(m['sloid']), str(m['osm_node_id'])) for m in exact_matches}
    
    # 2. Route-only matching
    print("2. Running route-only matching...")
    unmatched_df_for_route = atlas_df.copy()
    route_matches, _used = perform_unified_route_matching(
        unmatched_df_for_route,
        all_nodes,
        osm_xml_file=os.path.join('data', 'raw', 'osm_data.xml'),
        used_osm_nodes=set(),
        max_distance=50,
    )
    route_pairs = {(str(m['sloid']), str(m['osm_node_id'])) for m in route_matches if str(m['osm_node_id']) != 'NA'}
    
    # 3. Combined analysis
    print("3. Analyzing combination and effectiveness...")
    
    # Analyze token availability
    token_stats = analyze_route_matching_tokens()
    
    # Compute overlap metrics
    intersection = exact_pairs & route_pairs
    only_exact = exact_pairs - route_pairs
    only_route = route_pairs - exact_pairs
    union = exact_pairs | route_pairs
    
    # Quality analysis: check distances for route matches
    route_distances = [float(m.get('distance_m', 0)) for m in route_matches if pd.notna(m.get('distance_m'))]
    
    # Analyze match types in route matching
    route_match_types = {}
    for m in route_matches:
        match_type = m.get('match_type', 'unknown')
        route_match_types[match_type] = route_match_types.get(match_type, 0) + 1
    
    # Coverage analysis by operator
    route_matches_by_operator = {}
    for m in route_matches:
        operator = str(m.get('csv_business_org_abbr', 'unknown')).strip()
        if operator not in route_matches_by_operator:
            route_matches_by_operator[operator] = 0
        route_matches_by_operator[operator] += 1
    
    # Effectiveness metrics
    effectiveness = {
        # Basic counts
        'total_atlas_stops': len(atlas_df),
        'exact_matches': len(exact_pairs),
        'route_matches': len(route_pairs),
        'combined_matches': len(union),
        
        # Overlap analysis
        'intersection_size': len(intersection),
        'exact_only': len(only_exact),
        'route_only': len(only_route),
        'jaccard_similarity': len(intersection) / len(union) if union else 0.0,
        'route_coverage_of_exact': len(intersection) / len(exact_pairs) if exact_pairs else 0.0,
        'exact_coverage_of_route': len(intersection) / len(route_pairs) if route_pairs else 0.0,
        
        # Route matching effectiveness
        'route_precision': len(intersection) / len(route_pairs) if route_pairs else 0.0,
        'route_recall_vs_exact': len(intersection) / len(exact_pairs) if exact_pairs else 0.0,
        'route_added_value': len(only_route) / len(atlas_df) if atlas_df is not None else 0.0,
        
        # Quality metrics
        'route_match_distance_mean': np.mean(route_distances) if route_distances else 0.0,
        'route_match_distance_median': np.median(route_distances) if route_distances else 0.0,
        'route_match_distance_p90': np.percentile(route_distances, 90) if route_distances else 0.0,
        'route_matches_under_25m': sum(1 for d in route_distances if d <= 25) / len(route_distances) if route_distances else 0.0,
        
        # Token availability
        **token_stats,
        
        # Match type breakdown
        'route_match_types': route_match_types,
        'route_matches_by_operator': route_matches_by_operator,
        
        # Strategic insights
        'route_matching_efficiency': len(route_pairs) / len(atlas_df),
        'complementarity_factor': len(only_route) / len(only_exact) if only_exact else float('inf'),
    }
    
    print("\n=== KEY EFFECTIVENESS METRICS ===")
    print(f"Route matching found {len(route_pairs):,} pairs vs {len(exact_pairs):,} exact pairs")
    print(f"Jaccard similarity: {effectiveness['jaccard_similarity']:.3f}")
    print(f"Route precision (how many route matches are also exact): {effectiveness['route_precision']:.3f}")
    print(f"Route added value (new matches as % of total stops): {effectiveness['route_added_value']:.3f}")
    print(f"Average distance for route matches: {effectiveness['route_match_distance_mean']:.1f}m")
    print(f"Route matches within 25m: {effectiveness['route_matches_under_25m']:.3f}")
    
    # Save detailed results
    with open(os.path.join(out_dir, 'route_effectiveness_analysis.json'), 'w', encoding='utf-8') as f:
        json.dump(effectiveness, f, ensure_ascii=False, indent=2)
    
    # Save samples for manual inspection
    intersection_sample = list(intersection)[:100]
    only_route_sample = list(only_route)[:100]
    only_exact_sample = list(only_exact)[:100]
    
    samples = {
        'intersection_sample': intersection_sample,
        'only_route_sample': only_route_sample,
        'only_exact_sample': only_exact_sample,
    }
    
    with open(os.path.join(out_dir, 'route_effectiveness_samples.json'), 'w', encoding='utf-8') as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to {out_dir}")
    return effectiveness


if __name__ == '__main__':
    analyze_route_matching_effectiveness()
