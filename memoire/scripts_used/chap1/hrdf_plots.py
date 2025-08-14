#!/usr/bin/env python3
import os
import matplotlib.pyplot as plt
import numpy as np

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    figdir = os.path.join(root, 'memoire', 'figures', 'plots')
    os.makedirs(figdir, exist_ok=True)
    plt.rcParams['figure.dpi'] = 180

    wgs = os.path.join(root, 'data', 'raw', 'GLEISE_WGS')
    coords = []
    sloids = []
    current_sloid = None
    with open(wgs, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if ' g A ch:1:sloid:' in line or line.strip().startswith('g A ch:1:sloid:'):
                parts = line.split()
                for p in parts:
                    if p.startswith('ch:1:sloid:'):
                        current_sloid = p
                        break
            elif ' k ' in line and current_sloid:
                parts = line.split()
                try:
                    k_idx = parts.index('k')
                    lon = float(parts[k_idx+1]); lat = float(parts[k_idx+2])
                    sloids.append(current_sloid); coords.append((lon, lat))
                except Exception:
                    pass

    if coords:
        lon = np.array([c[0] for c in coords]); lat = np.array([c[1] for c in coords])
        fig, ax = plt.subplots(figsize=(7.2, 6))
        ax.scatter(lon, lat, s=0.2, alpha=0.35, c='tab:orange', rasterized=True)
        ax.set_title('HRDF GLEISE_WGS Quays – Switzerland')
        ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
        ax.grid(True, linewidth=0.2, alpha=0.2)
        fig.tight_layout(); fig.savefig(os.path.join(figdir, 'hrdf_quays_switzerland.png'), bbox_inches='tight')
        plt.close(fig)

        G_LON_MIN, G_LON_MAX = 6.05, 6.20
        G_LAT_MIN, G_LAT_MAX = 46.15, 46.30
        mask = (lon>=G_LON_MIN)&(lon<=G_LON_MAX)&(lat>=G_LAT_MIN)&(lat<=G_LAT_MAX)
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(lon[mask], lat[mask], s=2, alpha=0.7, c='tab:orange', rasterized=True)
        ax.set_title(f'HRDF Quays – Genève (zoom) — {int(mask.sum()):,} stops')
        ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
        ax.set_xlim(G_LON_MIN, G_LON_MAX); ax.set_ylim(G_LAT_MIN, G_LAT_MAX)
        ax.grid(True, linewidth=0.2, alpha=0.2)
        fig.tight_layout(); fig.savefig(os.path.join(figdir, 'hrdf_quays_geneva.png'), bbox_inches='tight')
        plt.close(fig)

    # Directions per SLOID (names)
    import pandas as pd
    hpath = os.path.join(root, 'data', 'processed', 'atlas_routes_hrdf.csv')
    if os.path.exists(hpath):
        h = pd.read_csv(hpath)
        gr = h.dropna(subset=['sloid', 'direction_name']).groupby('sloid')['direction_name'].nunique()
        if len(gr) > 0:
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.hist(gr.values, bins=np.arange(1, gr.max() + 2) - 0.5, color='tab:orange', alpha=0.85)
            ax.set_title('HRDF: #directions par SLOID (noms)')
            ax.set_xlabel('#directions uniques'); ax.set_ylabel('SLOIDs')
            fig.tight_layout(); fig.savefig(os.path.join(figdir, 'hrdf_directions_per_sloid.png'), bbox_inches='tight')
            plt.close(fig)

if __name__ == '__main__':
    main()


