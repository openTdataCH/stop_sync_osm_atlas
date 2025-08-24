import os
import json
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import time
from datetime import datetime


def ensure_dirs():
    out_dir = os.path.join('memoire', 'data', 'processed', 'chap4')
    fig_dir = os.path.join('memoire', 'figures', 'chap4')
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(fig_dir, exist_ok=True)
    return out_dir, fig_dir


def load_data():
    print("Loading data files...")
    start_time = time.time()
    
    print("  Loading unified routes CSV...")
    unified = pd.read_csv(os.path.join('data', 'processed', 'atlas_routes_unified.csv'), dtype=str)
    unified = unified.replace({'nan': np.nan})
    print(f"  Loaded {len(unified):,} unified route records")
    
    print("  Loading OSM routes CSV...")
    try:
        osm_routes = pd.read_csv(os.path.join('data', 'processed', 'osm_nodes_with_routes.csv'), dtype=str)
        print(f"  Loaded {len(osm_routes):,} OSM route records")
    except Exception:
        osm_routes = pd.DataFrame(columns=['node_id', 'gtfs_route_id', 'direction_id', 'route_name', 'uic_ref'])
        print("  No OSM routes file found, using empty DataFrame")
    
    elapsed = time.time() - start_time
    print(f"Data loading completed in {elapsed:.1f} seconds\n")
    return unified, osm_routes


def build_gtfs_tokens(unified: pd.DataFrame):
    print("Building GTFS tokens...")
    start_time = time.time()
    
    g = unified[unified['source'] == 'gtfs'].copy()
    if g.empty:
        print("  No GTFS data found")
        return set(), {}
    
    print(f"  Processing {len(g):,} GTFS records")
    g['route_norm'] = g['route_id_normalized'].where(g['route_id_normalized'].notna() & (g['route_id_normalized'] != ''), g['route_id'])
    g['direction_id'] = g['direction_id'].where(g['direction_id'].notna() & (g['direction_id'] != ''), np.nan)
    tokens = set()
    by_sloid_count = {}
    
    unique_sloids = g['sloid'].unique()
    print(f"  Processing {len(unique_sloids):,} unique SLOIDs")
    
    for i, (sloid, sub) in enumerate(g.groupby('sloid')):
        if i % 1000 == 0 and i > 0:
            print(f"    Processed {i:,} / {len(unique_sloids):,} SLOIDs ({i/len(unique_sloids)*100:.1f}%)")
        
        loc_tokens = set()
        for _, r in sub.iterrows():
            rid = r.get('route_norm')
            did = r.get('direction_id')
            if pd.notna(rid) and pd.notna(did):
                tokens.add((rid, did))
                loc_tokens.add((rid, did))
        by_sloid_count[sloid] = len(loc_tokens)
    
    elapsed = time.time() - start_time
    print(f"  Found {len(tokens):,} unique GTFS route tokens in {elapsed:.1f} seconds\n")
    return tokens, by_sloid_count


def normalize_route_id(route_id: str) -> str:
    if not route_id or pd.isna(route_id):
        return None
    import re
    return re.sub(r'-j\d+', '-jXX', str(route_id))


def build_osm_tokens(osm_routes: pd.DataFrame):
    print("Building OSM tokens...")
    start_time = time.time()
    
    toks = set()
    by_node_count = {}
    if osm_routes is None or osm_routes.empty:
        print("  No OSM route data available")
        return toks, by_node_count
    
    unique_nodes = osm_routes['node_id'].unique()
    print(f"  Processing {len(osm_routes):,} OSM route records across {len(unique_nodes):,} nodes")
    
    for i, (node_id, sub) in enumerate(osm_routes.groupby('node_id')):
        if i % 5000 == 0 and i > 0:
            print(f"    Processed {i:,} / {len(unique_nodes):,} nodes ({i/len(unique_nodes)*100:.1f}%)")
        
        loc = set()
        for _, r in sub.iterrows():
            rid = r.get('gtfs_route_id')
            did = r.get('direction_id')
            if pd.notna(rid) and pd.notna(did) and str(rid).strip():
                rid_norm = normalize_route_id(rid)
                toks.add((rid, did))
                if rid_norm:
                    toks.add((rid_norm, did))
                loc.add((rid, did))
        by_node_count[str(node_id)] = len(loc)
    
    elapsed = time.time() - start_time
    print(f"  Found {len(toks):,} unique OSM route tokens in {elapsed:.1f} seconds\n")
    return toks, by_node_count


def parse_osm_direction_uic_strings(xml_path: str):
    """Parse OSM XML to extract direction UIC strings. This is the most time-consuming operation."""
    strings = set()
    overall_start = time.time()
    
    print(f"🔍 Parsing OSM XML for direction UIC strings...")
    print(f"📁 File: {xml_path}")
    
    # Check file size for better progress estimation
    try:
        file_size = os.path.getsize(xml_path) / (1024 * 1024)  # MB
        print(f"📊 File size: {file_size:.1f} MB")
    except:
        pass
    
    # Parse XML
    parse_start = time.time()
    print("⏳ Loading and parsing XML (this may take 1-2 minutes)...")
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        parse_elapsed = time.time() - parse_start
        print(f"✅ XML parsed successfully in {parse_elapsed:.1f} seconds")
    except Exception as e:
        print(f"❌ Error parsing XML: {e}")
        return strings

    # Extract node UIC references
    node_start = time.time()
    print("\n🔍 Phase 1/2: Extracting node UIC references...")
    node_id_to_uic = {}
    nodes = root.findall('.//node')
    total_nodes = len(nodes)
    print(f"📊 Found {total_nodes:,} nodes to process")
    
    last_progress_time = time.time()
    for i, node in enumerate(nodes):
        current_time = time.time()
        
        # Show progress every 25,000 nodes or every 10 seconds
        if i % 25000 == 0 or (current_time - last_progress_time) >= 10:
            if i > 0:
                elapsed = current_time - node_start
                rate = i / elapsed if elapsed > 0 else 0
                remaining = (total_nodes - i) / rate if rate > 0 else 0
                progress_pct = (i / total_nodes) * 100
                print(f"    📈 {i:,} / {total_nodes:,} nodes ({progress_pct:.1f}%) | "
                      f"Rate: {rate:.0f} nodes/sec | ETA: {remaining/60:.1f} min")
            last_progress_time = current_time
        
        nid = node.get('id')
        for tag in node.findall('./tag'):
            if tag.get('k') == 'uic_ref':
                node_id_to_uic[nid] = tag.get('v')
                break

    node_elapsed = time.time() - node_start
    print(f"✅ Phase 1 complete: Found {len(node_id_to_uic):,} nodes with UIC references in {node_elapsed:.1f} seconds")

    # Process route relations
    rel_start = time.time()
    print(f"\n🔍 Phase 2/2: Processing route relations...")
    relations = root.findall('.//relation')
    total_relations = len(relations)
    print(f"📊 Found {total_relations:,} relations to process")
    
    route_count = 0
    last_progress_time = time.time()
    
    for i, relation in enumerate(relations):
        current_time = time.time()
        
        # Show progress every 500 relations or every 5 seconds
        if i % 500 == 0 or (current_time - last_progress_time) >= 5:
            if i > 0:
                elapsed = current_time - rel_start
                rate = i / elapsed if elapsed > 0 else 0
                remaining = (total_relations - i) / rate if rate > 0 else 0
                progress_pct = (i / total_relations) * 100
                print(f"    📈 {i:,} / {total_relations:,} relations ({progress_pct:.1f}%) | "
                      f"Routes found: {route_count:,} | Rate: {rate:.0f} rel/sec | ETA: {remaining/60:.1f} min")
            last_progress_time = current_time
        
        is_route = any(tag.get('k') == 'type' and tag.get('v') == 'route' for tag in relation.findall('./tag'))
        if not is_route:
            continue
        
        route_count += 1
        member_nodes = [m.get('ref') for m in relation.findall("./member[@type='node']")]
        # Skip if sequence looks noisy (too few or no UICs at ends)
        if len(member_nodes) >= 3:
            first_uic = node_id_to_uic.get(member_nodes[0])
            last_uic = node_id_to_uic.get(member_nodes[-1])
            if first_uic and last_uic and first_uic != last_uic:
                strings.add(f"{first_uic} → {last_uic}")
    
    rel_elapsed = time.time() - rel_start
    overall_elapsed = time.time() - overall_start
    
    print(f"✅ Phase 2 complete: Processed {total_relations:,} relations in {rel_elapsed:.1f} seconds")
    print(f"🎯 TOTAL: Found {len(strings):,} unique direction UIC strings from {route_count:,} routes")
    print(f"⏱️  Overall time: {overall_elapsed:.1f} seconds ({overall_elapsed/60:.1f} minutes)\n")
    
    return strings


def build_hrdf_dir_uic_set(unified: pd.DataFrame):
    print("Building HRDF direction UIC set...")
    start_time = time.time()
    
    h = unified[unified['source'] == 'hrdf']
    if h.empty:
        print("  No HRDF data found")
        return set()
    
    print(f"  Processing {len(h):,} HRDF records")
    result = set(h['direction_uic'].dropna().unique())
    
    elapsed = time.time() - start_time
    print(f"  Found {len(result):,} unique HRDF direction UIC strings in {elapsed:.1f} seconds\n")
    return result


def make_plots(fig_dir, atlas_by_sloid_cover):
    s = pd.Series(atlas_by_sloid_cover)
    if not s.empty:
        desc = {
            'count': int(s.count()),
            'mean': round(float(s.mean()), 3),
            'median': round(float(s.median()), 3),
            'p10': round(float(s.quantile(0.10)), 3),
            'p90': round(float(s.quantile(0.90)), 3),
            'max': int(s.max()),
        }
        print("[SUMMARY] GTFS token coverage per SLOID:", desc)
    plt.figure(figsize=(6, 4), dpi=150)
    if s.empty:
        # Render a clear placeholder rather than an empty/blank plot
        plt.axis('off')
        plt.text(0.5, 0.5, 'No per-SLOID coverage data available', ha='center', va='center', fontsize=11)
    else:
        s.clip(upper=30).hist(bins=30, color='#f28e2b', alpha=0.85)
        plt.title('Route token coverage in OSM per SLOID (GTFS) (clipped at 30)')
        plt.xlabel('Number of GTFS tokens present in OSM')
        plt.ylabel('Number of SLOIDs')
    plt.tight_layout()
    plt.savefig(os.path.join(fig_dir, 'hist_route_token_coverage_per_sloid.png'))
    plt.close()


def make_jaccard_plots(fig_dir: str, total_gtfs_tokens: int, total_osm_tokens: int, overlap_tokens: int, jaccard: float):
    """Generate simple explanatory plots for Jaccard similarity.

    Produces:
      - jaccard_sets_bars.png: bar chart of |GTFS|, |OSM|, |overlap|, |union|
      - jaccard_sets_circles.png: two translucent circles illustrating overlap
    """
    union = total_gtfs_tokens + total_osm_tokens - overlap_tokens

    # Bars
    plt.figure(figsize=(6, 4), dpi=150)
    labels = ['|GTFS|', '|OSM|', '|Overlap|', '|Union|']
    values = [total_gtfs_tokens, total_osm_tokens, overlap_tokens, union]
    colors = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759']
    plt.bar(labels, values, color=colors, alpha=0.9)
    for i, v in enumerate(values):
        plt.text(i, v, f"{v:,}", ha='center', va='bottom', fontsize=9)
    plt.title(f'GTFS vs OSM route tokens — Jaccard = {jaccard:.3f}')
    plt.ylabel('Count')
    plt.tight_layout()
    plt.savefig(os.path.join(fig_dir, 'jaccard_sets_bars.png'))
    plt.close()

    # Circles (schematic, not to scale but proportional radii)
    plt.figure(figsize=(6, 4), dpi=150)
    ax = plt.gca()
    ax.set_aspect('equal')
    ax.axis('off')

    # Compute radii proportional to sqrt(size) for area proportionality
    # Normalize so that larger circle radius ~1.0
    gtfs_size = max(total_gtfs_tokens, 1)
    osm_size = max(total_osm_tokens, 1)
    max_size = max(gtfs_size, osm_size)
    r_gtfs = np.sqrt(gtfs_size / max_size)
    r_osm = np.sqrt(osm_size / max_size)

    # Place circles with partial overlap proportionally to Jaccard (heuristic)
    # Desired overlap area fraction approx = overlap/union.
    # Use simple spacing heuristic: more overlap -> centers closer.
    center_distance = max(0.2, (1.8 * (1 - jaccard)))

    c1 = Circle((0.5 - center_distance/2, 0.5), r_gtfs, color='#4e79a7', alpha=0.35, ec='#4e79a7')
    c2 = Circle((0.5 + center_distance/2, 0.5), r_osm, color='#f28e2b', alpha=0.35, ec='#f28e2b')
    ax.add_patch(c1)
    ax.add_patch(c2)

    # Annotations
    ax.text(0.5 - center_distance/2 - r_gtfs, 0.5 + r_gtfs + 0.05, f"GTFS\n{total_gtfs_tokens:,}", ha='center', va='bottom', fontsize=9, color='#1f3b59')
    ax.text(0.5 + center_distance/2 + r_osm, 0.5 + r_osm + 0.05, f"OSM\n{total_osm_tokens:,}", ha='center', va='bottom', fontsize=9, color='#7a3c06')
    ax.text(0.5, 0.1, f"Overlap: {overlap_tokens:,}    Union: {union:,}\nJaccard = Overlap / Union = {jaccard:.3f}", ha='center', va='center', fontsize=10)

    plt.tight_layout()
    plt.savefig(os.path.join(fig_dir, 'jaccard_sets_circles.png'))
    plt.close()


def main(skip_slow_per_sloid=False):
    """
    Main analysis function.
    
    Args:
        skip_slow_per_sloid (bool): If True, skips the slow per-SLOID coverage computation
                                   and only computes fast alternative statistics
    """
    script_start = time.time()
    print("=" * 80)
    print("🚀 ROUTE MATCHING STATISTICS ANALYSIS")
    print("=" * 80)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if skip_slow_per_sloid:
        print("⚡ FAST MODE: Skipping slow per-SLOID computation")
    print()
    
    out_dir, fig_dir = ensure_dirs()
    unified, osm_routes = load_data()

    # Build token sets
    gtfs_tokens, gtfs_tokens_per_sloid = build_gtfs_tokens(unified)
    osm_tokens, _ = build_osm_tokens(osm_routes)
    
    # Calculate overlaps
    print("🔄 Calculating token overlaps...")
    overlap_start = time.time()
    overlap_tokens = len(gtfs_tokens & osm_tokens)
    total_gtfs_tokens = len(gtfs_tokens)
    total_osm_tokens = len(osm_tokens)
    jaccard = (overlap_tokens / (total_gtfs_tokens + total_osm_tokens - overlap_tokens)) if (total_gtfs_tokens + total_osm_tokens - overlap_tokens) else 0.0
    overlap_elapsed = time.time() - overlap_start
    print(f"  Overlap calculation completed in {overlap_elapsed:.1f} seconds\n")

    # Per SLOID coverage: how many of its GTFS tokens appear anywhere in OSM
    if skip_slow_per_sloid:
        print("⏩ SKIPPING slow per-SLOID loop; computing optimized vectorized coverage instead")
        coverage_start = time.time()
        g = unified[unified['source'] == 'gtfs'].copy()
        if g.empty:
            coverage_per_sloid = {}
            coverage_stats = {'total_sloids_with_coverage': 0, 'total_sloids': 0, 'coverage_rate': 0, 'avg_tokens_covered_per_sloid': 0, 'max_tokens_covered': 0}
            route_coverage_stats = {'unique_gtfs_routes': 0, 'gtfs_routes_with_osm_match': 0, 'route_match_rate': 0}
        else:
            g['route_norm'] = g['route_id_normalized'].where(g['route_id_normalized'].notna() & (g['route_id_normalized'] != ''), g['route_id'])
            g['direction_id'] = g['direction_id'].where(g['direction_id'].notna() & (g['direction_id'] != ''), np.nan)

            g_valid = g[g['route_norm'].notna() & g['direction_id'].notna()].copy()
            if g_valid.empty:
                coverage_per_sloid = {}
                coverage_stats = {'total_sloids_with_coverage': 0, 'total_sloids': 0, 'coverage_rate': 0, 'avg_tokens_covered_per_sloid': 0, 'max_tokens_covered': 0}
                route_coverage_stats = {'unique_gtfs_routes': 0, 'gtfs_routes_with_osm_match': 0, 'route_match_rate': 0}
            else:
                g_valid['token'] = list(zip(g_valid['route_norm'], g_valid['direction_id']))
                g_valid['in_osm'] = g_valid['token'].apply(lambda x: x in osm_tokens)

                coverage_per_sloid = (
                    g_valid[g_valid['in_osm']]
                    .groupby('sloid')['token']
                    .nunique()
                    .to_dict()
                )
                # Include zeros for SLOIDs with no coverage
                for sloid in gtfs_tokens_per_sloid.keys():
                    if sloid not in coverage_per_sloid:
                        coverage_per_sloid[sloid] = 0

                coverage_values = list(coverage_per_sloid.values())
                coverage_stats = {
                    'total_sloids_with_coverage': sum(1 for x in coverage_values if x > 0),
                    'total_sloids': len(coverage_values),
                    'coverage_rate': sum(1 for x in coverage_values if x > 0) / len(coverage_values) if coverage_values else 0,
                    'avg_tokens_covered_per_sloid': sum(coverage_values) / len(coverage_values) if coverage_values else 0,
                    'max_tokens_covered': max(coverage_values) if coverage_values else 0,
                }

                g_tokens = set(zip(g_valid['route_norm'], g_valid['direction_id']))
                route_coverage_stats = {
                    'unique_gtfs_routes': len(set(g_valid['route_norm'])),
                    'gtfs_routes_with_osm_match': len(set(r for r, d in g_tokens if (r, d) in osm_tokens)),
                }
                route_coverage_stats['route_match_rate'] = route_coverage_stats['gtfs_routes_with_osm_match'] / route_coverage_stats['unique_gtfs_routes'] if route_coverage_stats['unique_gtfs_routes'] > 0 else 0

        coverage_elapsed = time.time() - coverage_start
        print(f"  ⚡ OPTIMIZED: Coverage calculation completed in {coverage_elapsed:.1f} seconds\n")
        
    else:
        print("📊 Computing per-SLOID coverage...")
        coverage_start = time.time()
        
        # OPTIMIZATION: Pre-process GTFS data once instead of filtering for each SLOID
        print("  Pre-processing GTFS data...")
        g = unified[unified['source'] == 'gtfs'].copy()
        if g.empty:
            print("  No GTFS data found for coverage calculation")
            coverage_per_sloid = {}
        else:
            g['route_norm'] = g['route_id_normalized'].where(g['route_id_normalized'].notna() & (g['route_id_normalized'] != ''), g['route_id'])
            g['direction_id'] = g['direction_id'].where(g['direction_id'].notna() & (g['direction_id'] != ''), np.nan)
            
            # Filter out rows without valid route/direction
            g_valid = g[g['route_norm'].notna() & g['direction_id'].notna()].copy()
            print(f"  Found {len(g_valid):,} valid GTFS records for coverage analysis")
            
            # Create tokens column for vectorized operations
            g_valid['token'] = list(zip(g_valid['route_norm'], g_valid['direction_id']))
            
            # Pre-compute which tokens exist in OSM (vectorized set membership)
            g_valid['in_osm'] = g_valid['token'].apply(lambda x: x in osm_tokens)
            
            print("  Computing coverage per SLOID...")
            # Group by SLOID and count unique tokens that exist in OSM
            coverage_per_sloid = (
                g_valid[g_valid['in_osm']]
                .groupby('sloid')['token']
                .nunique()
                .to_dict()
            )
            
            # Ensure all SLOIDs are represented (even those with 0 coverage)
            for sloid in gtfs_tokens_per_sloid.keys():
                if sloid not in coverage_per_sloid:
                    coverage_per_sloid[sloid] = 0
        
        coverage_elapsed = time.time() - coverage_start
        print(f"  ⚡ OPTIMIZED: Coverage calculation completed in {coverage_elapsed:.1f} seconds\n")
        
        # ALTERNATIVE FAST STATISTIC: Overall GTFS-OSM token overlap summary
        print("⚡ Computing fast alternative statistics...")
        fast_start = time.time()
        
        # Alternative 1: Token coverage distribution (much faster than per-SLOID)
        if coverage_per_sloid:
            coverage_values = list(coverage_per_sloid.values())
            coverage_stats = {
                'total_sloids_with_coverage': sum(1 for x in coverage_values if x > 0),
                'total_sloids': len(coverage_values),
                'coverage_rate': sum(1 for x in coverage_values if x > 0) / len(coverage_values) if coverage_values else 0,
                'avg_tokens_covered_per_sloid': sum(coverage_values) / len(coverage_values) if coverage_values else 0,
                'max_tokens_covered': max(coverage_values) if coverage_values else 0,
            }
        else:
            coverage_stats = {'total_sloids_with_coverage': 0, 'total_sloids': 0, 'coverage_rate': 0, 'avg_tokens_covered_per_sloid': 0, 'max_tokens_covered': 0}
        
        # Alternative 2: Route-level statistics (faster than SLOID-level)
        if not g.empty and 'g_valid' in locals():
            g_tokens = set(zip(g_valid['route_norm'], g_valid['direction_id']))
            route_coverage_stats = {
                'unique_gtfs_routes': len(set(g_valid['route_norm'])),
                'gtfs_routes_with_osm_match': len(set(r for r, d in g_tokens if (r, d) in osm_tokens)),
            }
            if route_coverage_stats['unique_gtfs_routes'] > 0:
                route_coverage_stats['route_match_rate'] = route_coverage_stats['gtfs_routes_with_osm_match'] / route_coverage_stats['unique_gtfs_routes']
            else:
                route_coverage_stats['route_match_rate'] = 0
        else:
            route_coverage_stats = {'unique_gtfs_routes': 0, 'gtfs_routes_with_osm_match': 0, 'route_match_rate': 0}
        
        fast_elapsed = time.time() - fast_start
        print(f"  Fast statistics completed in {fast_elapsed:.1f} seconds\n")

    # HRDF overlap of direction UIC strings (this is the slowest part)
    osm_dir_uic_strings = parse_osm_direction_uic_strings(os.path.join('data', 'raw', 'osm_data.xml'))
    hrdf_dir_uic = build_hrdf_dir_uic_set(unified)
    
    print("🔄 Computing HRDF-OSM UIC overlap...")
    uic_start = time.time()
    overlap_dir_uic = len(hrdf_dir_uic & osm_dir_uic_strings)
    uic_elapsed = time.time() - uic_start
    print(f"  UIC overlap calculation completed in {uic_elapsed:.1f} seconds\n")

    # Save JSON summary
    print("💾 Saving results...")
    save_start = time.time()
    summary = {
        # Core token statistics
        'gtfs_tokens_total': total_gtfs_tokens,
        'osm_tokens_total': total_osm_tokens,
        'gtfs_tokens_overlapping_with_osm': overlap_tokens,
        'gtfs_osm_token_jaccard': round(jaccard, 4),
        
        # Per-SLOID detailed coverage (expensive to compute)
        'per_sloid_gtfs_token_coverage': {
            'mean': float(pd.Series(coverage_per_sloid).mean()) if coverage_per_sloid else 0.0,
            'median': float(pd.Series(coverage_per_sloid).median()) if coverage_per_sloid else 0.0,
            'p90': float(pd.Series(coverage_per_sloid).quantile(0.9)) if coverage_per_sloid else 0.0,
        },
        
        # Fast alternative statistics (efficient to compute)
        'sloid_coverage_summary': coverage_stats,
        'route_coverage_summary': route_coverage_stats,
        
        # UIC direction strings
        'hrdf_dir_uic_total': len(hrdf_dir_uic),
        'osm_dir_uic_total': len(osm_dir_uic_strings),
        'hrdf_osm_dir_uic_overlap': overlap_dir_uic,
    }
    
    output_file = os.path.join(out_dir, 'route_matching_stats.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("📈 Generating plots...")
    make_plots(fig_dir, coverage_per_sloid)
    make_jaccard_plots(fig_dir, total_gtfs_tokens, total_osm_tokens, overlap_tokens, jaccard)
    
    save_elapsed = time.time() - save_start
    total_elapsed = time.time() - script_start
    
    print(f"  Saving completed in {save_elapsed:.1f} seconds")
    print(f"\n✅ ANALYSIS COMPLETE!")
    print(f"📁 Results saved to: {out_dir}")
    print(f"⏱️  Total execution time: {total_elapsed:.1f} seconds ({total_elapsed/60:.1f} minutes)")
    print(f"⏰ Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


def main_fast():
    """Run analysis in fast mode, skipping slow per-SLOID computation."""
    main(skip_slow_per_sloid=True)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--fast':
        print("🚀 Running in FAST mode (use --fast flag)")
        main_fast()
    else:
        print("🐌 Running in FULL mode (use --fast flag for faster execution)")
        main()


