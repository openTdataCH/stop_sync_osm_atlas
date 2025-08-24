import os
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


GENEVA_BBOX = {
    'min_lat': 46.17,
    'max_lat': 46.30,
    'min_lon': 6.04,
    'max_lon': 6.20,
}


def ensure_dirs():
    fig_dir = os.path.join('memoire', 'figures', 'chap4')
    os.makedirs(fig_dir, exist_ok=True)
    return fig_dir


def in_bbox(lat, lon, bbox=GENEVA_BBOX):
    return (
        (lat >= bbox['min_lat']) and (lat <= bbox['max_lat']) and
        (lon >= bbox['min_lon']) and (lon <= bbox['max_lon'])
    )


def load_atlas():
    path = os.path.join('data', 'raw', 'stops_ATLAS.csv')
    df = pd.read_csv(path, sep=';')
    df['wgs84North'] = pd.to_numeric(df['wgs84North'], errors='coerce')
    df['wgs84East'] = pd.to_numeric(df['wgs84East'], errors='coerce')
    df = df.dropna(subset=['wgs84North', 'wgs84East'])
    return df[['sloid', 'wgs84North', 'wgs84East']]


def load_unified():
    path = os.path.join('data', 'processed', 'atlas_routes_unified.csv')
    df = pd.read_csv(path, dtype=str)
    df = df.replace({'nan': np.nan})
    return df


def plot_geneva_points(points, title, out_path, s=5, alpha=0.5, color='#1f77b4'):
    if not points:
        print(f"No points to plot for {title}")
        return
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    plt.figure(figsize=(6, 5), dpi=150)
    plt.scatter(lons, lats, s=s, alpha=alpha, c=color, edgecolors='none')
    plt.title(title)
    plt.xlabel('Longitude')
    plt.ylabel('Latitude')
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
    print(f"Saved figure to {out_path}")


def plot_osm_geneva(fig_dir):
    xml_path = os.path.join('data', 'raw', 'osm_data.xml')
    csv_routes = os.path.join('data', 'processed', 'osm_nodes_with_routes.csv')
    nodes_in_routes = set()
    try:
        df = pd.read_csv(csv_routes)
        nodes_in_routes = set(df['node_id'].astype(str).unique())
    except Exception:
        pass
    points_on = []
    points_off = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for node in root.iter('node'):
            node_id = node.get('id')
            try:
                lat = float(node.get('lat'))
                lon = float(node.get('lon'))
            except Exception:
                continue
            if in_bbox(lat, lon):
                if node_id in nodes_in_routes:
                    points_on.append((lat, lon))
                else:
                    points_off.append((lat, lon))
    except Exception as e:
        print('Error loading OSM XML:', e)
    out_on = os.path.join(fig_dir, 'geneva_osm_routes_nodes.png')
    out_off = os.path.join(fig_dir, 'geneva_osm_non_routes_nodes.png')
    plot_geneva_points(points_on, 'OSM: Nodes on routes (Geneva area)', out_on, color='#e15759')
    plot_geneva_points(points_off, 'OSM: Nodes not on routes (Geneva area)', out_off, color='#9e9e9e')


def plot_gtfs_geneva(fig_dir):
    unified = load_unified()
    atlas = load_atlas()
    gtfs_sloids = set(unified.loc[unified['source'] == 'gtfs', 'sloid'].dropna().astype(str).unique())
    sub = atlas[atlas['sloid'].astype(str).isin(gtfs_sloids)].copy()
    points = []
    for _, r in sub.iterrows():
        lat = float(r['wgs84North'])
        lon = float(r['wgs84East'])
        if in_bbox(lat, lon):
            points.append((lat, lon))
    out_path = os.path.join(fig_dir, 'geneva_gtfs_sloids.png')
    plot_geneva_points(points, 'GTFS: SLOIDs with routes (Geneva area)', out_path, color='#1f77b4')


def plot_hrdf_geneva(fig_dir):
    unified = load_unified()
    atlas = load_atlas()
    hrdf_sloids = set(unified.loc[unified['source'] == 'hrdf', 'sloid'].dropna().astype(str).unique())
    sub = atlas[atlas['sloid'].astype(str).isin(hrdf_sloids)].copy()
    points = []
    for _, r in sub.iterrows():
        lat = float(r['wgs84North'])
        lon = float(r['wgs84East'])
        if in_bbox(lat, lon):
            points.append((lat, lon))
    out_path = os.path.join(fig_dir, 'geneva_hrdf_sloids.png')
    plot_geneva_points(points, 'HRDF: SLOIDs with lines (Geneva area)', out_path, color='#59a14f')


def main():
    fig_dir = ensure_dirs()
    plot_osm_geneva(fig_dir)
    plot_gtfs_geneva(fig_dir)
    plot_hrdf_geneva(fig_dir)


if __name__ == '__main__':
    main()


