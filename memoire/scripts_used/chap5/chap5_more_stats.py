import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sqlalchemy import create_engine


def get_engine():
    database_uri = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
    return create_engine(database_uri)


def load_stops(engine):
    q = """
        SELECT id, sloid, stop_type, match_type, distance_m,
               atlas_lat, atlas_lon, osm_lat, osm_lon,
               osm_node_type
        FROM stops
    """
    df = pd.read_sql(q, engine)
    return df


def detect_suspicious_large_distances(df: pd.DataFrame, threshold=500.0) -> pd.DataFrame:
    matched = df[(df['stop_type'] == 'matched') & df['distance_m'].notnull()]
    return matched[matched['distance_m'] > threshold].sort_values('distance_m', ascending=False)


def coverage_buckets(df: pd.DataFrame) -> pd.DataFrame:
    matched = df[(df['stop_type'] == 'matched') & df['distance_m'].notnull()]
    bins = [0, 5, 10, 20, 50, 100, 200, 500, np.inf]
    labels = ['≤5', '5-10', '10-20', '20-50', '50-100', '100-200', '200-500', '>500']
    matched['bucket'] = pd.cut(matched['distance_m'], bins=bins, labels=labels, right=True, include_lowest=True)
    tbl = matched['bucket'].value_counts().reindex(labels, fill_value=0).reset_index()
    tbl.columns = ['bucket', 'count']
    tbl['pct'] = tbl['count'] / tbl['count'].sum() * 100.0
    return tbl


def plot_coverage_bars(tbl: pd.DataFrame, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    plt.figure(figsize=(8, 4))
    plt.bar(tbl['bucket'].astype(str), tbl['pct'], color='#4C78A8')
    plt.ylabel('Pourcentage des correspondances (%)')
    plt.xlabel('Tranche de distance (m)')
    plt.title('Répartition des correspondances par tranche de distance')
    for i, v in enumerate(tbl['pct']):
        plt.text(i, v + 0.5, f'{v:.1f}%', ha='center', fontsize=8)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'distance_coverage_buckets.png'), dpi=180)
    plt.close()


def main():
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../figures/chap6'))
    os.makedirs(out_dir, exist_ok=True)
    engine = get_engine()
    df = load_stops(engine)

    # Suspicious long distances
    suspicious = detect_suspicious_large_distances(df, threshold=300.0)
    suspicious[['sloid', 'distance_m']].to_csv(os.path.join(out_dir, 'suspicious_long_distances.csv'), index=False)

    # Coverage buckets
    buckets = coverage_buckets(df)
    buckets.to_csv(os.path.join(out_dir, 'distance_coverage_buckets.csv'), index=False)
    plot_coverage_bars(buckets, out_dir)


if __name__ == '__main__':
    main()


