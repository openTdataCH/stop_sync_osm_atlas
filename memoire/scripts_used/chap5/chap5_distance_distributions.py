import os
import math
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sqlalchemy import create_engine


def get_engine():
    database_uri = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
    return create_engine(database_uri)


def load_matched_stops(engine):
    query = """
        SELECT distance_m, match_type, osm_node_type
        FROM stops
        WHERE stop_type = 'matched' AND distance_m IS NOT NULL
    """
    df = pd.read_sql(query, engine)
    # Clean distance outliers (negative or absurd)
    df = df[(df['distance_m'] >= 0) & (df['distance_m'] < 10000)]
    return df


def summarize_by_method(df: pd.DataFrame) -> pd.DataFrame:
    def pct(series, t):
        return (series <= t).mean() * 100.0

    grouped = df.groupby('match_type')['distance_m']
    summary = grouped.agg(
        count='count',
        mean='mean',
        median='median',
        p90=lambda s: np.percentile(s, 90),
        p95=lambda s: np.percentile(s, 95),
        p99=lambda s: np.percentile(s, 99),
    ).reset_index()
    # Add quality thresholds
    thresholds = [5, 10, 20, 50, 100]
    for t in thresholds:
        summary[f'pct_≤{t}m'] = grouped.apply(lambda s, tt=t: pct(s, tt)).values
    return summary


def plot_histograms(df: pd.DataFrame, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    # Global distribution (log x)
    plt.figure(figsize=(8, 5))
    plt.hist(df['distance_m'], bins=100, color='#4C78A8', alpha=0.85)
    plt.xscale('log')
    plt.xlabel('Distance (m, échelle log)')
    plt.ylabel('Fréquence')
    plt.title('Distribution globale des distances (toutes méthodes)')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'distances_global_hist.png'), dpi=180)
    plt.close()

    # Overlay by method (linear up to 200m)
    plt.figure(figsize=(8, 5))
    for method, color in zip(sorted(df['match_type'].dropna().unique()), ['#4C78A8', '#F58518', '#54A24B', '#E45756', '#72B7B2']):
        subset = df[df['match_type'] == method]
        subset = subset[subset['distance_m'] <= 200]
        plt.hist(subset['distance_m'], bins=40, alpha=0.5, label=method, density=True)
    plt.xlabel('Distance (m)')
    plt.ylabel('Densité')
    plt.title('Distribution des distances par méthode (≤ 200 m)')
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'distances_by_method_hist_0_200.png'), dpi=180)
    plt.close()

    # Boxplot by method
    methods = list(sorted(df['match_type'].dropna().unique()))
    data = [df[df['match_type'] == m]['distance_m'] for m in methods]
    plt.figure(figsize=(9, 5))
    plt.boxplot(data, labels=methods, showfliers=False)
    plt.ylabel('Distance (m)')
    plt.title('Distances par méthode (boîtes, sans valeurs extrêmes)')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'distances_by_method_box.png'), dpi=180)
    plt.close()


def plot_by_osm_node_type(df: pd.DataFrame, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    top_types = (
        df['osm_node_type']
        .fillna('inconnu')
        .value_counts()
        .head(8)
        .index.tolist()
    )
    subset = df[df['osm_node_type'].fillna('inconnu').isin(top_types)].copy()
    subset['osm_node_type'] = subset['osm_node_type'].fillna('inconnu')
    order = subset.groupby('osm_node_type')['distance_m'].median().sort_values().index.tolist()

    # Boxplot by node type
    data = [subset[subset['osm_node_type'] == t]['distance_m'] for t in order]
    plt.figure(figsize=(10, 5))
    plt.boxplot(data, labels=order, showfliers=False)
    plt.ylabel('Distance (m)')
    plt.title('Distances par type de nœud OSM (top 8, sans valeurs extrêmes)')
    plt.xticks(rotation=20, ha='right')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'distances_by_osm_node_type_box.png'), dpi=180)
    plt.close()


def main():
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../figures/chap6'))
    os.makedirs(out_dir, exist_ok=True)

    engine = get_engine()
    df = load_matched_stops(engine)

    summary = summarize_by_method(df)
    summary_path = os.path.join(out_dir, 'distance_summary_by_method.csv')
    summary.to_csv(summary_path, index=False)

    plot_histograms(df, out_dir)
    plot_by_osm_node_type(df, out_dir)

    # Also save a compact Markdown table for LaTeX verbatim inclusion
    md_lines = [
        '| méthode | n | moyenne (m) | médiane (m) | p90 | p95 | p99 | ≤10m | ≤20m | ≤50m | ≤100m |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for _, row in summary.iterrows():
        md_lines.append(
            f"| {row['match_type']} | {int(row['count'])} | {row['mean']:.2f} | {row['median']:.2f} | {row['p90']:.2f} | {row['p95']:.2f} | {row['p99']:.2f} | {row['pct_≤10m']:.1f}% | {row['pct_≤20m']:.1f}% | {row['pct_≤50m']:.1f}% | {row['pct_≤100m']:.1f}% |"
        )
    with open(os.path.join(out_dir, 'distance_summary_by_method.md'), 'w') as f:
        f.write('\n'.join(md_lines))


if __name__ == '__main__':
    main()


