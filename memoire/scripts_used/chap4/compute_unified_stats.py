import os
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def ensure_dirs():
    out_dir = os.path.join('memoire', 'data', 'processed', 'chap4')
    fig_dir = os.path.join('memoire', 'figures', 'chap4')
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(fig_dir, exist_ok=True)
    return out_dir, fig_dir


def load_unified_csv():
    path = os.path.join('data', 'processed', 'atlas_routes_unified.csv')
    if not os.path.exists(path):
        raise FileNotFoundError(f"Expected file not found: {path}")
    df = pd.read_csv(path, dtype=str)
    # Normalize helpful columns
    for col in ['sloid', 'source', 'route_id', 'route_id_normalized', 'direction_id', 'direction_name', 'line_name', 'direction_uic']:
        if col in df.columns:
            df[col] = df[col].astype(str)
    # Replace 'nan' strings with NaN for numeric ops
    df = df.replace({'nan': np.nan})
    return df


def compute_gtfs_stats(df: pd.DataFrame):
    g = df[df['source'] == 'gtfs'].copy()
    if g.empty:
        return {}
    # Prefer normalized route id when present
    g['route_norm'] = g['route_id_normalized'].where(g['route_id_normalized'].notna() & (g['route_id_normalized'] != ''), g['route_id'])

    sloids_with_gtfs = g['sloid'].dropna().nunique()

    # Unique routes per sloid
    routes_per_sloid = (
        g.dropna(subset=['sloid', 'route_norm'])
         .groupby('sloid')['route_norm']
         .nunique()
    )
    avg_routes = float(routes_per_sloid.mean()) if not routes_per_sloid.empty else 0.0
    med_routes = float(routes_per_sloid.median()) if not routes_per_sloid.empty else 0.0

    # Unique (route, direction) per sloid
    g_rd = g.dropna(subset=['sloid', 'route_norm'])
    g_rd['direction_id'] = g_rd['direction_id'].where(g_rd['direction_id'].notna() & (g_rd['direction_id'] != ''), np.nan)
    rd_per_sloid = (
        g_rd.groupby('sloid')[['route_norm', 'direction_id']]
            .apply(lambda x: set(map(tuple, x.values)))
            .apply(len)
    )
    avg_rd = float(rd_per_sloid.mean()) if not rd_per_sloid.empty else 0.0
    med_rd = float(rd_per_sloid.median()) if not rd_per_sloid.empty else 0.0

    # Duplicate groups for (sloid, route_norm, direction)
    grp = g_rd.groupby(['sloid', 'route_norm', 'direction_id']).size()
    if len(grp) > 0:
        dup_groups_pct = float((grp.gt(1).sum() / len(grp)) * 100.0)
    else:
        dup_groups_pct = 0.0

    # Groups exhibiting multiple distinct direction strings even for same route+dir
    # Count groups where same (sloid, route_norm, direction_id) has >1 distinct direction_name
    multi_dirname_groups = 0
    total_groups = 0
    if not g_rd.empty:
        for (s, r, d), sub in g_rd.groupby(['sloid', 'route_norm', 'direction_id']):
            total_groups += 1
            distinct_names = sub['direction_name'].dropna().unique()
            if len(distinct_names) > 1:
                multi_dirname_groups += 1
    multi_dirname_pct = float((multi_dirname_groups / total_groups) * 100.0) if total_groups else 0.0

    return {
        'sloids_with_gtfs': int(sloids_with_gtfs),
        'avg_unique_routes_per_sloid': round(avg_routes, 2),
        'median_unique_routes_per_sloid': round(med_routes, 2),
        'avg_unique_route_direction_per_sloid': round(avg_rd, 2),
        'median_unique_route_direction_per_sloid': round(med_rd, 2),
        'duplicate_groups_pct_route_norm_direction': round(dup_groups_pct, 2),
        'multi_direction_name_for_same_route_dir_pct': round(multi_dirname_pct, 2),
        'routes_per_sloid_series': routes_per_sloid,
        'route_dir_per_sloid_series': rd_per_sloid,
    }


def compute_hrdf_stats(df: pd.DataFrame):
    h = df[df['source'] == 'hrdf'].copy()
    if h.empty:
        return {}
    sloids_with_hrdf = h['sloid'].dropna().nunique()

    # Unique lines per sloid
    lines_per_sloid = (
        h.dropna(subset=['sloid', 'line_name'])
         .groupby('sloid')['line_name']
         .nunique()
    )
    avg_lines = float(lines_per_sloid.mean()) if not lines_per_sloid.empty else 0.0
    med_lines = float(lines_per_sloid.median()) if not lines_per_sloid.empty else 0.0

    # Distinct directions per (sloid, line_name)
    by_pair = h.dropna(subset=['sloid', 'line_name']).groupby(['sloid', 'line_name'])
    distinct_dir_uic = by_pair['direction_uic'].apply(lambda s: s.dropna().nunique()) if 'direction_uic' in h.columns else pd.Series(dtype=float)
    distinct_dir_name = by_pair['direction_name'].apply(lambda s: s.dropna().nunique()) if 'direction_name' in h.columns else pd.Series(dtype=float)

    avg_dir_uic = float(distinct_dir_uic.mean()) if not distinct_dir_uic.empty else 0.0
    med_dir_uic = float(distinct_dir_uic.median()) if not distinct_dir_uic.empty else 0.0
    avg_dir_name = float(distinct_dir_name.mean()) if not distinct_dir_name.empty else 0.0
    med_dir_name = float(distinct_dir_name.median()) if not distinct_dir_name.empty else 0.0

    # Extreme cases: pairs showing >= 30 distinct UIC pairs
    extreme_pairs = int((distinct_dir_uic >= 30).sum()) if not distinct_dir_uic.empty else 0
    top_examples = []
    if not distinct_dir_uic.empty:
        top = distinct_dir_uic.sort_values(ascending=False).head(10)
        for (s, l), cnt in top.items():
            top_examples.append({'sloid': s, 'line_name': l, 'distinct_uic_directions': int(cnt)})

    return {
        'sloids_with_hrdf': int(sloids_with_hrdf),
        'avg_unique_lines_per_sloid': round(avg_lines, 2),
        'median_unique_lines_per_sloid': round(med_lines, 2),
        'avg_distinct_directions_per_sloid_line_uic': round(avg_dir_uic, 2),
        'median_distinct_directions_per_sloid_line_uic': round(med_dir_uic, 2),
        'avg_distinct_directions_per_sloid_line_name': round(avg_dir_name, 2),
        'median_distinct_directions_per_sloid_line_name': round(med_dir_name, 2),
        'num_pairs_with_30plus_distinct_uic_directions': int(extreme_pairs),
        'top_pairs_by_distinct_uic_directions': top_examples,
        'lines_per_sloid_series': lines_per_sloid,
    }


def compute_overlap(df: pd.DataFrame):
    sloids_gtfs = set(df.loc[df['source'] == 'gtfs', 'sloid'].dropna().unique())
    sloids_hrdf = set(df.loc[df['source'] == 'hrdf', 'sloid'].dropna().unique())
    inter = sloids_gtfs & sloids_hrdf
    only_gtfs = sloids_gtfs - sloids_hrdf
    only_hrdf = sloids_hrdf - sloids_gtfs
    return {
        'gtfs_only_sloids': len(only_gtfs),
        'hrdf_only_sloids': len(only_hrdf),
        'both_gtfs_and_hrdf_sloids': len(inter),
    }


def save_outputs(out_dir, stats):
    json_path = os.path.join(out_dir, 'unified_stats.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # Also write a small markdown summary for easy inclusion
    md_path = os.path.join(out_dir, 'unified_stats.md')
    lines = []
    g = stats.get('gtfs', {})
    h = stats.get('hrdf', {})
    o = stats.get('overlap', {})
    lines.append('# Unified Routes Statistics (auto-generated)')
    if g:
        lines.append('## GTFS')
        lines.append(f"SLOIDs with GTFS routes: {g.get('sloids_with_gtfs', 0):,}")
        lines.append(f"Avg unique routes per sloid: {g.get('avg_unique_routes_per_sloid', 0)} (median {g.get('median_unique_routes_per_sloid', 0)})")
        lines.append(f"Avg unique (route, direction) per sloid: {g.get('avg_unique_route_direction_per_sloid', 0)} (median {g.get('median_unique_route_direction_per_sloid', 0)})")
        lines.append(f"Duplicate groups for (sloid, route_norm, direction): {g.get('duplicate_groups_pct_route_norm_direction', 0)}%")
        lines.append(f"Groups with multiple distinct direction strings for same route+dir: {g.get('multi_direction_name_for_same_route_dir_pct', 0)}%")
    if h:
        lines.append('## HRDF')
        lines.append(f"SLOIDs with HRDF lines: {h.get('sloids_with_hrdf', 0):,}")
        lines.append(f"Avg unique lines per sloid: {h.get('avg_unique_lines_per_sloid', 0)} (median {h.get('median_unique_lines_per_sloid', 0)})")
        lines.append(f"Avg distinct directions per (sloid,line_name) by UIC: {h.get('avg_distinct_directions_per_sloid_line_uic', 0)} (median {h.get('median_distinct_directions_per_sloid_line_uic', 0)})")
        lines.append(f"Avg distinct directions per (sloid,line_name) by name: {h.get('avg_distinct_directions_per_sloid_line_name', 0)} (median {h.get('median_distinct_directions_per_sloid_line_name', 0)})")
        lines.append(f"Pairs with ≥30 distinct first→last UIC directions: {h.get('num_pairs_with_30plus_distinct_uic_directions', 0)}")
    if o:
        lines.append('## Overlap')
        lines.append(f"GTFS-only sloids: {o.get('gtfs_only_sloids', 0):,}")
        lines.append(f"HRDF-only sloids: {o.get('hrdf_only_sloids', 0):,}")
        lines.append(f"Both GTFS and HRDF sloids: {o.get('both_gtfs_and_hrdf_sloids', 0):,}")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def make_plots(fig_dir, stats):
    # GTFS histograms
    g = stats.get('gtfs', {})
    if g and isinstance(g.get('routes_per_sloid_series'), pd.Series):
        s = g['routes_per_sloid_series']
        plt.figure(figsize=(6, 4), dpi=150)
        s.clip(upper=20).hist(bins=20, color='#1f77b4', alpha=0.8)
        plt.title('GTFS: unique routes per SLOID (clipped at 20)')
        plt.xlabel('Unique routes')
        plt.ylabel('Number of SLOIDs')
        plt.tight_layout()
        plt.savefig(os.path.join(fig_dir, 'hist_gtfs_routes_per_sloid.png'))
        plt.close()
    if g and isinstance(g.get('route_dir_per_sloid_series'), pd.Series):
        s = g['route_dir_per_sloid_series']
        plt.figure(figsize=(6, 4), dpi=150)
        s.clip(upper=30).hist(bins=30, color='#4e79a7', alpha=0.8)
        plt.title('GTFS: unique (route, direction) per SLOID (clipped at 30)')
        plt.xlabel('(route, direction) unique count')
        plt.ylabel('Number of SLOIDs')
        plt.tight_layout()
        plt.savefig(os.path.join(fig_dir, 'hist_gtfs_route_dir_per_sloid.png'))
        plt.close()

    # HRDF histogram
    h = stats.get('hrdf', {})
    if h and isinstance(h.get('lines_per_sloid_series'), pd.Series):
        s = h['lines_per_sloid_series']
        plt.figure(figsize=(6, 4), dpi=150)
        s.clip(upper=20).hist(bins=20, color='#59a14f', alpha=0.8)
        plt.title('HRDF: unique lines per SLOID (clipped at 20)')
        plt.xlabel('Unique lines')
        plt.ylabel('Number of SLOIDs')
        plt.tight_layout()
        plt.savefig(os.path.join(fig_dir, 'hist_hrdf_lines_per_sloid.png'))
        plt.close()


def main():
    out_dir, fig_dir = ensure_dirs()
    df = load_unified_csv()
    stats = {
        'gtfs': compute_gtfs_stats(df),
        'hrdf': compute_hrdf_stats(df),
        'overlap': compute_overlap(df),
    }
    # Remove non-serializable series before saving JSON
    for k in ('gtfs', 'hrdf'):
        if k in stats and isinstance(stats[k], dict):
            stats[k].pop('routes_per_sloid_series', None)
            stats[k].pop('route_dir_per_sloid_series', None)
            stats[k].pop('lines_per_sloid_series', None)
    save_outputs(out_dir, stats)
    # Recompute for plotting (needs series)
    df2 = load_unified_csv()
    plot_stats = {
        'gtfs': compute_gtfs_stats(df2),
        'hrdf': compute_hrdf_stats(df2),
    }
    make_plots(fig_dir, plot_stats)
    print('Wrote unified stats to', out_dir)


if __name__ == '__main__':
    main()


