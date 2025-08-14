#!/usr/bin/env python3
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    figdir = os.path.join(root, 'memoire', 'figures', 'plots')
    os.makedirs(figdir, exist_ok=True)
    plt.rcParams['figure.dpi'] = 180

    # Maps
    stops_path = os.path.join(root, 'data', 'raw', 'gtfs', 'stops.txt')
    df = pd.read_csv(stops_path, dtype={'stop_id': str, 'stop_lat': float, 'stop_lon': float})
    ch = df[df['stop_id'].str.startswith('85')]
    lon = ch['stop_lon']; lat = ch['stop_lat']

    fig, ax = plt.subplots(figsize=(7.2, 6))
    ax.scatter(lon, lat, s=0.2, alpha=0.35, c='tab:gray', rasterized=True)
    ax.set_title('GTFS Stops (WGS84) – Switzerland')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    ax.grid(True, linewidth=0.2, alpha=0.2)
    fig.tight_layout(); fig.savefig(os.path.join(figdir, 'gtfs_points_switzerland.png'), bbox_inches='tight')
    plt.close(fig)

    G_LON_MIN, G_LON_MAX = 6.05, 6.20
    G_LAT_MIN, G_LAT_MAX = 46.15, 46.30
    mask = lon.between(G_LON_MIN, G_LON_MAX) & lat.between(G_LAT_MIN, G_LAT_MAX)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(lon[mask], lat[mask], s=2, alpha=0.7, c='tab:olive', rasterized=True)
    ax.set_title(f'GTFS Stops – Genève (zoom) — {int(mask.sum()):,} stops')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    ax.set_xlim(G_LON_MIN, G_LON_MAX); ax.set_ylim(G_LAT_MIN, G_LAT_MAX)
    ax.grid(True, linewidth=0.2, alpha=0.2)
    fig.tight_layout(); fig.savefig(os.path.join(figdir, 'gtfs_points_geneva.png'), bbox_inches='tight')
    plt.close(fig)

    # Routes per SLOID histogram
    gtfs_routes = os.path.join(root, 'data', 'processed', 'atlas_routes_gtfs.csv')
    g = pd.read_csv(gtfs_routes)
    gr = g.dropna(subset=['sloid', 'route_id']).groupby('sloid')['route_id'].nunique()
    if len(gr) > 0:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(gr.values, bins=np.arange(1, gr.max() + 2) - 0.5, color='tab:blue', alpha=0.85)
        ax.set_title('GTFS: distribution du nombre de lignes par SLOID')
        ax.set_xlabel('nombre de lignes uniques'); ax.set_ylabel('SLOIDs')
        ax.set_xlim(0, 40)
        fig.tight_layout(); fig.savefig(os.path.join(figdir, 'gtfs_routes_per_sloid.png'), bbox_inches='tight')
        plt.close(fig)

if __name__ == '__main__':
    main()


