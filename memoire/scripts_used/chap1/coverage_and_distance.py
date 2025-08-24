#!/usr/bin/env python3
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from math import radians, sin, cos, sqrt, atan2

def hav(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    figdir = os.path.join(root, 'memoire', 'figures', 'plots')
    os.makedirs(figdir, exist_ok=True)
    plt.rcParams['figure.dpi'] = 180

    # Coverage bar: GTFS vs HRDF
    p_unified = os.path.join(root, 'data', 'processed', 'atlas_routes_unified.csv')
    vals = {}
    if os.path.exists(p_unified):
        unified = pd.read_csv(p_unified)
        vals['GTFS_sloids'] = unified[unified['source'] == 'gtfs']['sloid'].dropna().nunique()
        vals['HRDF_sloids'] = unified[unified['source'] == 'hrdf']['sloid'].dropna().nunique()
    if vals:
        labels = list(vals.keys()); values = list(vals.values())
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.bar(labels, values, color=['tab:blue', 'tab:orange'][:len(values)])
        ax.set_title('Couverture des SLOIDs: GTFS vs HRDF')
        for i, v in enumerate(values):
            ax.text(i, v, f"{v:,}", ha='center', va='bottom', fontsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(figdir, 'sloid_coverage_gtfs_hrdf.png'), bbox_inches='tight')
        plt.close(fig)

    # Distance histogram: ATLAS ↔ GTFS UIC centroid
    atlas_path = os.path.join(root, 'data', 'raw', 'stops_ATLAS.csv')
    stops_path = os.path.join(root, 'data', 'raw', 'gtfs', 'stops.txt')
    if os.path.exists(atlas_path) and os.path.exists(stops_path):
        atlas = pd.read_csv(atlas_path, sep=';').dropna(subset=['wgs84North', 'wgs84East', 'number'])
        atlas['number'] = atlas['number'].astype(str)
        stops = pd.read_csv(stops_path, dtype=str)
        stops['uic'] = stops['stop_id'].str.split(':').str[0]
        stops_ch = stops[stops['uic'].str.startswith('85', na=False)].copy()
        stops_ch['stop_lat'] = stops_ch['stop_lat'].astype(float)
        stops_ch['stop_lon'] = stops_ch['stop_lon'].astype(float)
        centroids = stops_ch.groupby('uic').agg({'stop_lat': 'mean', 'stop_lon': 'mean'}).reset_index()
        mrg = atlas.merge(centroids, left_on='number', right_on='uic', how='inner')
        if not mrg.empty:
            dists = [hav(a, b, c, d) for a, b, c, d in zip(mrg['wgs84North'], mrg['wgs84East'], mrg['stop_lat'], mrg['stop_lon'])]
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.hist(np.array(dists), bins=50, color='tab:cyan', alpha=0.9)
            ax.set_title('Distance ATLAS vs GTFS centroid (par UIC)')
            ax.set_xlabel('Distance [m]'); ax.set_ylabel('Comptes')
            ax.set_xlim(0, 500)
            fig.tight_layout(); fig.savefig(os.path.join(figdir, 'atlas_vs_gtfs_distance_hist.png'), bbox_inches='tight')
            plt.close(fig)

if __name__ == '__main__':
    main()


