#!/usr/bin/env python3
import os
import pandas as pd
import matplotlib.pyplot as plt


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    figdir = os.path.join(root, 'memoire', 'figures', 'plots')
    os.makedirs(figdir, exist_ok=True)
    plt.rcParams['figure.dpi'] = 180

    atlas_path = os.path.join(root, 'data', 'raw', 'stops_ATLAS.csv')
    unified_path = os.path.join(root, 'data', 'processed', 'atlas_routes_unified.csv')

    if not (os.path.exists(atlas_path) and os.path.exists(unified_path)):
        raise SystemExit('Required inputs missing')

    atlas = pd.read_csv(atlas_path, sep=';').dropna(subset=['sloid', 'wgs84North', 'wgs84East'])
    atlas['sloid'] = atlas['sloid'].astype(str)
    atlas['wgs84North'] = atlas['wgs84North'].astype(float)
    atlas['wgs84East'] = atlas['wgs84East'].astype(float)

    unified = pd.read_csv(unified_path)
    sloids_gtfs = set(unified[unified['source'] == 'gtfs']['sloid'].dropna().astype(str).str.strip())
    sloids_hrdf = set(unified[unified['source'] == 'hrdf']['sloid'].dropna().astype(str).str.strip())

    # Join to get coordinates
    gtfs_pts = atlas[atlas['sloid'].isin(sloids_gtfs)][['wgs84East', 'wgs84North']].rename(columns={'wgs84East': 'lon', 'wgs84North': 'lat'})
    hrdf_pts = atlas[atlas['sloid'].isin(sloids_hrdf)][['wgs84East', 'wgs84North']].rename(columns={'wgs84East': 'lon', 'wgs84North': 'lat'})

    # Geneva bbox
    G_LON_MIN, G_LON_MAX = 6.05, 6.20
    G_LAT_MIN, G_LAT_MAX = 46.15, 46.30

    def in_geneva(df):
        return df[(df['lon'] >= G_LON_MIN) & (df['lon'] <= G_LON_MAX) & (df['lat'] >= G_LAT_MIN) & (df['lat'] <= G_LAT_MAX)]

    gtfs_ge = in_geneva(gtfs_pts)
    hrdf_ge = in_geneva(hrdf_pts)

    # Plot side-by-side
    fig, ax = plt.subplots(1, 2, figsize=(14.4, 6))
    ax[0].scatter(gtfs_ge['lon'], gtfs_ge['lat'], s=6, alpha=0.8, c='tab:olive', rasterized=True)
    ax[0].set_title(f'GTFS matched SLOIDs — Genève — {len(gtfs_ge):,}')
    ax[0].set_xlim(G_LON_MIN, G_LON_MAX); ax[0].set_ylim(G_LAT_MIN, G_LAT_MAX)
    ax[0].set_xlabel('Longitude'); ax[0].set_ylabel('Latitude')
    ax[0].grid(True, linewidth=0.2, alpha=0.2)

    ax[1].scatter(hrdf_ge['lon'], hrdf_ge['lat'], s=6, alpha=0.8, c='tab:orange', rasterized=True)
    ax[1].set_title(f'HRDF matched SLOIDs — Genève — {len(hrdf_ge):,}')
    ax[1].set_xlim(G_LON_MIN, G_LON_MAX); ax[1].set_ylim(G_LAT_MIN, G_LAT_MAX)
    ax[1].set_xlabel('Longitude'); ax[1].set_ylabel('Latitude')
    ax[1].grid(True, linewidth=0.2, alpha=0.2)

    fig.tight_layout()
    out = os.path.join(figdir, 'geneva_matched_sloids_gtfs_hrdf.png')
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)

    # Also print coverage stats to console
    print('GTFS matched SLOIDs total:', len(sloids_gtfs))
    print('HRDF matched SLOIDs total:', len(sloids_hrdf))
    print('GTFS matched SLOIDs in Geneva bbox:', len(gtfs_ge))
    print('HRDF matched SLOIDs in Geneva bbox:', len(hrdf_ge))


if __name__ == '__main__':
    main()


