import os
import json
import pandas as pd
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


def main(max_distance_m=50):
    out_dir = ensure_dirs()
    atlas_df = load_atlas_df()
    all_nodes, uic_ref_dict, _name_index = parse_osm_xml(os.path.join('data', 'raw', 'osm_data.xml'))

    # 1) Exact-only matching
    exact_matches, exact_unmatched, used_osm_exact = exact_matching(atlas_df, uic_ref_dict)

    # 2) Route-only matching (on the full ATLAS set)
    unmatched_df_for_route = atlas_df.copy()
    route_matches, _used = perform_unified_route_matching(
        unmatched_df_for_route,
        all_nodes,
        osm_xml_file=os.path.join('data', 'raw', 'osm_data.xml'),
        used_osm_nodes=set(),
        max_distance=max_distance_m,
    )

    # Normalize outputs for comparison
    def to_pairs(records):
        pairs = set()
        for r in records:
            s = str(r.get('sloid'))
            n = str(r.get('osm_node_id'))
            if s and n and n != 'NA':
                pairs.add((s, n))
        return pairs

    exact_pairs = to_pairs(exact_matches)
    route_pairs = to_pairs(route_matches)

    # Compute metrics
    inter = exact_pairs & route_pairs
    only_exact = exact_pairs - route_pairs
    only_route = route_pairs - exact_pairs

    summary = {
        'exact_total_pairs': len(exact_pairs),
        'route_total_pairs': len(route_pairs),
        'intersection_pairs': len(inter),
        'jaccard_similarity': (len(inter) / (len(exact_pairs) + len(route_pairs) - len(inter))) if (len(exact_pairs) + len(route_pairs) - len(inter)) else 0.0,
        'exact_only_pairs': len(only_exact),
        'route_only_pairs': len(only_route),
        'exact_coverage_over_route': (len(inter) / len(route_pairs)) if route_pairs else 0.0,
        'route_coverage_over_exact': (len(inter) / len(exact_pairs)) if exact_pairs else 0.0,
    }

    print("=== EXACT vs ROUTE matching (route-only vs exact-only) ===")
    for k, v in summary.items():
        print(f"{k}: {v}")

    # Save JSON with a small sample of disagreements for inspection
    disagreements = {
        'only_exact_sample': list(sorted(list(only_exact)))[:200],
        'only_route_sample': list(sorted(list(only_route)))[:200],
    }

    with open(os.path.join(out_dir, 'exact_vs_route_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, 'exact_vs_route_disagreements_sample.json'), 'w', encoding='utf-8') as f:
        json.dump(disagreements, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()


