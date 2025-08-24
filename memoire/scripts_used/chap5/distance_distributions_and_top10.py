import os
import math
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
import matplotlib.pyplot as plt
import seaborn as sns


def get_database_uri() -> str:
    return os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')


def ensure_dirs():
    out_dir = os.path.join('memoire', 'figures', 'chap5')
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def load_matched_data(engine) -> pd.DataFrame:
    query = """
        SELECT
            s.distance_m,
            s.match_type,
            s.uic_ref AS atlas_uic,
            s.sloid,
            o.osm_uic_ref AS osm_uic,
            a.atlas_designation_official,
            a.atlas_designation,
            o.osm_uic_name,
            o.osm_name
        FROM stops s
        LEFT JOIN atlas_stops a ON a.sloid = s.sloid
        LEFT JOIN osm_nodes o ON o.osm_node_id = s.osm_node_id
        WHERE s.stop_type = 'matched'
    """
    df = pd.read_sql(query, engine)
    # Normalize numeric
    df['distance_m'] = pd.to_numeric(df['distance_m'], errors='coerce')
    # OSM official designation preference: uic_name then name
    df['osm_official'] = df['osm_uic_name'].fillna('').replace('', np.nan)
    df['osm_official'] = df['osm_official'].fillna(df['osm_name'])
    # ATLAS official fallback to designation
    df['atlas_official'] = df['atlas_designation_official'].fillna('')
    df['atlas_official'] = df['atlas_official'].replace('', np.nan).fillna(df['atlas_designation'])
    return df


def map_match_type_group(mt: str) -> str:
    if not isinstance(mt, str):
        return 'other'
    if mt == 'exact':
        return 'Exact'
    if mt == 'name':
        return 'Name'
    if mt.startswith('distance_matching_1_'):
        return 'Distance stage 1'
    if mt == 'distance_matching_2':
        return 'Distance stage 2'
    if mt in ('distance_matching_3a', 'distance_matching_3b'):
        return 'Distance stage 3'
    if mt.startswith('route_unified_gtfs'):
        return 'Route GTFS'
    if mt.startswith('route_unified_hrdf'):
        return 'Route HRDF'
    return 'other'


def plot_histograms(df: pd.DataFrame, out_dir: str):
    # Filter distances to [0, 50] for comparability (methods other than Exact/Name are capped at 50m)
    data = df.dropna(subset=['distance_m']).copy()
    data = data[(data['distance_m'] >= 0) & (data['distance_m'] <= 50)]
    if data.empty:
        print('No distance data within 0-50m; skipping plots.')
        return

    data['method_group'] = data['match_type'].map(map_match_type_group)
    desired_order = [
        'Exact', 'Name', 'Distance stage 1', 'Distance stage 2', 'Distance stage 3', 'Route GTFS', 'Route HRDF'
    ]
    data = data[data['method_group'].isin(desired_order)]
    if data.empty:
        print('No data for specified method groups; skipping plots.')
        return

    # Consistent binning up to 50m
    bins = np.arange(0, 52, 2)

    # Faceted histogram grid (small multiples)
    n_groups = len(desired_order)
    n_cols = 2
    n_rows = math.ceil(n_groups / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(n_cols * 6.0, n_rows * 3.6), constrained_layout=True)
    axes = np.array(axes).reshape(n_rows, n_cols)

    for idx, group in enumerate(desired_order):
        r, c = divmod(idx, n_cols)
        ax = axes[r, c]
        subset = data[data['method_group'] == group]
        if subset.empty:
            ax.set_visible(False)
            continue
        sns.histplot(subset['distance_m'], bins=bins, ax=ax, color='#4C78A8', edgecolor='white')
        ax.set_title(f"{group} (n={len(subset)})")
        ax.set_xlabel('Distance (m)')
        ax.set_ylabel('Count')
        ax.set_xlim(0, 50)

    # Hide any unused subplots
    for j in range(n_groups, n_rows * n_cols):
        r, c = divmod(j, n_cols)
        axes[r, c].set_visible(False)

    out_path = os.path.join(out_dir, 'distance_distributions_methods_0_50.png')
    fig.suptitle('Distributions des distances par méthode (coupure à 50 m)')
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    print(f"Saved histogram grid to {out_path}")


def latex_escape(s: str) -> str:
    if s is None:
        return ''
    # Minimal escaping
    return (
        str(s)
        .replace('\\', r'\textbackslash{}')
        .replace('&', r'\&')
        .replace('%', r'\%')
        .replace('$', r'\$')
        .replace('#', r'\#')
        .replace('_', r'\_')
        .replace('{', r'\{')
        .replace('}', r'\}')
        .replace('~', r'\textasciitilde{}')
        .replace('^', r'\textasciicircum{}')
    )


def export_top10_table(df: pd.DataFrame, out_dir: str):
    top = df.dropna(subset=['distance_m']).copy()
    top = top[top['distance_m'] >= 0]
    top = top.sort_values('distance_m', ascending=False).head(10)
    # Build display columns
    rows = []
    for _, r in top.iterrows():
        rows.append({
            'atlas_official': r.get('atlas_official'),
            'osm_official': r.get('osm_official'),
            'method': r.get('match_type'),
            'atlas_uic': r.get('atlas_uic'),
            'osm_uic': r.get('osm_uic'),
            'distance_m': r.get('distance_m'),
        })
    out_csv = os.path.join(out_dir, 'top10_distances.csv')
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"Saved CSV to {out_csv}")

    # LaTeX table (use tabularx and shorter method labels to avoid overflow); wrap in 0.8\textwidth minipage
    out_tex = os.path.join(out_dir, 'top10_distances_table.tex')
    with open(out_tex, 'w', encoding='utf-8') as f:
        f.write('% Auto-generated by distance_distributions_and_top10.py\n')
        f.write('\\begin{small}\n')
        f.write('\\begin{minipage}{0.8\\textwidth}\n')
        f.write('\\begin{tabularx}{\\textwidth}{>{\\raggedright\\arraybackslash}X >{\\raggedright\\arraybackslash}X >{\\raggedright\\arraybackslash}p{2.2cm} >{\\raggedright\\arraybackslash}p{3.0cm} r}\n')
        f.write('\\toprule\n')
        f.write('ATLAS (officiel) & OSM (officiel) & Méthode & UIC ATLAS / OSM & \\multicolumn{1}{c}{Distance (m)} \\\n')
        f.write('\\midrule\n')
        for row in rows:
            atlas_name = latex_escape(row['atlas_official'])
            osm_name = latex_escape(row['osm_official'])
            raw_method = (row['method'] or '')
            if isinstance(raw_method, str):
                if raw_method == 'exact':
                    disp_method = 'Exact'
                elif raw_method == 'name':
                    disp_method = 'Name'
                elif raw_method.startswith('distance_matching_1_'):
                    disp_method = 'Distance 1'
                elif raw_method == 'distance_matching_2':
                    disp_method = 'Distance 2'
                elif raw_method in ('distance_matching_3a', 'distance_matching_3b'):
                    disp_method = 'Distance 3'
                elif raw_method.startswith('route_unified_gtfs'):
                    disp_method = 'Route GTFS'
                elif raw_method.startswith('route_unified_hrdf'):
                    disp_method = 'Route HRDF'
                elif raw_method == 'exact_postpass':
                    disp_method = 'Exact (post)'
                else:
                    disp_method = raw_method.replace('_', ' ')
            else:
                disp_method = ''
            method = latex_escape(disp_method)
            atlas_uic = '' if pd.isna(row['atlas_uic']) else str(row['atlas_uic'])
            osm_uic = '' if pd.isna(row['osm_uic']) else str(row['osm_uic'])
            uic_pair = latex_escape(f"{atlas_uic} / {osm_uic}")
            dist_str = f"{float(row['distance_m']):.1f}" if not pd.isna(row['distance_m']) else ''
            f.write(f"{atlas_name} & {osm_name} & {method} & {uic_pair} & {dist_str} \\\n")
        f.write('\\bottomrule\n')
        f.write('\\end{tabularx}\n')
        f.write('\\end{minipage}\n')
        f.write('\\end{small}\n')
        print(f"Saved LaTeX table to {out_tex}")


def main():
    out_dir = ensure_dirs()
    engine = create_engine(get_database_uri())
    df = load_matched_data(engine)
    plot_histograms(df, out_dir)
    export_top10_table(df, out_dir)


if __name__ == '__main__':
    main()


