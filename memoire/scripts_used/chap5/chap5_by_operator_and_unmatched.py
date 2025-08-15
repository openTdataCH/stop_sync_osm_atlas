import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sqlalchemy import create_engine


def get_engine():
    database_uri = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
    return create_engine(database_uri)


def load_joined(engine):
    query = """
        SELECT s.distance_m, s.match_type, s.stop_type, s.sloid,
               a.atlas_business_org_abbr AS operator
        FROM stops s
        LEFT JOIN atlas_stops a ON s.sloid = a.sloid
    """
    df = pd.read_sql(query, engine)
    df['operator'] = df['operator'].fillna('Inconnu')
    return df


def operator_distance_stats(df: pd.DataFrame) -> pd.DataFrame:
    matched = df[(df['stop_type'] == 'matched') & df['distance_m'].notnull() & (df['distance_m'] >= 0)]
    grouped = matched.groupby('operator')['distance_m']
    out = grouped.agg(count='count', mean='mean', median='median', p90=lambda s: np.percentile(s, 90)).reset_index()
    out = out.sort_values('median')
    return out


def plot_operator_box(df: pd.DataFrame, out_dir: str, top_n: int = 15):
    os.makedirs(out_dir, exist_ok=True)
    matched = df[(df['stop_type'] == 'matched') & df['distance_m'].notnull() & (df['distance_m'] >= 0)]
    counts = matched['operator'].value_counts()
    top_ops = counts.head(top_n).index.tolist()
    subset = matched[matched['operator'].isin(top_ops)]
    order = subset.groupby('operator')['distance_m'].median().sort_values().index.tolist()
    data = [subset[subset['operator'] == op]['distance_m'] for op in order]
    plt.figure(figsize=(11, 5))
    plt.boxplot(data, labels=order, showfliers=False)
    plt.xticks(rotation=20, ha='right')
    plt.ylabel('Distance (m)')
    plt.title('Distances par opérateur (top {0}, sans valeurs extrêmes)'.format(top_n))
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, 'distances_by_operator_box.png'), dpi=180)
    plt.close()


def unmatched_with_nearby_counterparts(engine, radius_meters_list=(50, 100, 200)):
    # We count unmatched stops that have any matched stop within a radius using haversine on atlas coords.
    # Note: we assume unmatched have atlas coords.
    import pandas as pd
    import numpy as np

    # Pull minimal dataset for unmatched and matched with coordinates
    q_unmatched = """
        SELECT id, sloid, atlas_lat AS lat, atlas_lon AS lon
        FROM stops
        WHERE stop_type = 'unmatched' AND atlas_lat IS NOT NULL AND atlas_lon IS NOT NULL
    """
    q_matched = """
        SELECT id, sloid, atlas_lat AS lat, atlas_lon AS lon
        FROM stops
        WHERE stop_type = 'matched' AND atlas_lat IS NOT NULL AND atlas_lon IS NOT NULL
    """
    um = pd.read_sql(q_unmatched, engine)
    mt = pd.read_sql(q_matched, engine)

    if um.empty or mt.empty:
        results = []
        for r in radius_meters_list:
            results.append({'radius_m': r, 'unmatched_total': len(um), 'with_nearby_counterpart': 0, 'pct': 0.0})
        return pd.DataFrame(results)

    # Build a simple grid-based spatial index to accelerate neighbor search
    earth_radius_m = 6371000.0
    deg_per_meter_lat = 1.0 / (111_320.0)

    def lon_deg_per_meter_at_lat(lat_deg):
        return 1.0 / (111_320.0 * np.cos(np.radians(lat_deg)))

    # Choose grid ~50m cells for bucketing
    cell_m = 50.0
    um['cell_x'] = (um['lon'] * (1/deg_per_meter_lat) / cell_m).astype(int)
    um['cell_y'] = (um['lat'] / deg_per_meter_lat / cell_m).astype(int)
    mt['cell_x'] = (mt['lon'] * (1/deg_per_meter_lat) / cell_m).astype(int)
    mt['cell_y'] = (mt['lat'] / deg_per_meter_lat / cell_m).astype(int)

    # Build buckets for matched
    buckets = {}
    for _, row in mt.iterrows():
        key = (row['cell_x'], row['cell_y'])
        buckets.setdefault(key, []).append((row['lat'], row['lon']))

    def haversine(lat1, lon1, lat2, lon2):
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = np.sin(dlat/2.0)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2.0)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
        return earth_radius_m * c

    results = []
    for radius in radius_meters_list:
        nearby_count = 0
        neighbor_offsets = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        for _, row in um.iterrows():
            cx, cy = row['cell_x'], row['cell_y']
            lat1, lon1 = row['lat'], row['lon']
            found = False
            for dx, dy in neighbor_offsets:
                candidates = buckets.get((cx + dx, cy + dy), [])
                if not candidates:
                    continue
                for lat2, lon2 in candidates:
                    if haversine(lat1, lon1, lat2, lon2) <= radius:
                        found = True
                        break
                if found:
                    break
            if found:
                nearby_count += 1
        total = len(um)
        pct = (nearby_count / total * 100.0) if total > 0 else 0.0
        results.append({'radius_m': radius, 'unmatched_total': total, 'with_nearby_counterpart': nearby_count, 'pct': pct})

    return pd.DataFrame(results)


def main():
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../figures/chap6'))
    os.makedirs(out_dir, exist_ok=True)
    engine = get_engine()
    df = load_joined(engine)

    # Operator stats and plot
    op_stats = operator_distance_stats(df)
    op_stats.to_csv(os.path.join(out_dir, 'operator_distance_stats.csv'), index=False)
    plot_operator_box(df, out_dir)

    # Unmatched neighbors
    proximity = unmatched_with_nearby_counterparts(engine, radius_meters_list=(25, 50, 100, 200, 400))
    proximity.to_csv(os.path.join(out_dir, 'unmatched_proximity_stats.csv'), index=False)


if __name__ == '__main__':
    main()


