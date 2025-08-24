#!/usr/bin/env python3
import os
import pandas as pd
import matplotlib.pyplot as plt

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    figdir = os.path.join(root, 'memoire', 'figures', 'plots')
    os.makedirs(figdir, exist_ok=True)

    atlas_path = os.path.join(root, 'data', 'raw', 'stops_ATLAS.csv')
    df = pd.read_csv(atlas_path, sep=';')
    df = df.dropna(subset=['wgs84North', 'wgs84East'])
    lon = df['wgs84East'].astype(float)
    lat = df['wgs84North'].astype(float)

    plt.rcParams['figure.dpi'] = 180

    # National map
    fig, ax = plt.subplots(figsize=(7.2, 6))
    ax.scatter(lon, lat, s=0.2, alpha=0.35, c='tab:blue', rasterized=True)
    ax.set_title('ATLAS Boarding Platforms (WGS84) – Switzerland')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    ax.grid(True, linewidth=0.2, alpha=0.2)
    fig.tight_layout(); fig.savefig(os.path.join(figdir, 'atlas_points_switzerland.png'), bbox_inches='tight')
    plt.close(fig)

    # Geneva zoom
    G_LON_MIN, G_LON_MAX = 6.05, 6.20
    G_LAT_MIN, G_LAT_MAX = 46.15, 46.30
    mask = lon.between(G_LON_MIN, G_LON_MAX) & lat.between(G_LAT_MIN, G_LAT_MAX)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(lon[mask], lat[mask], s=2, alpha=0.7, c='tab:red', rasterized=True)
    ax.set_title(f'ATLAS Boarding Platforms – Genève (zoom) — {int(mask.sum()):,} stops')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    ax.set_xlim(G_LON_MIN, G_LON_MAX); ax.set_ylim(G_LAT_MIN, G_LAT_MAX)
    ax.grid(True, linewidth=0.2, alpha=0.2)
    fig.tight_layout(); fig.savefig(os.path.join(figdir, 'atlas_points_geneva.png'), bbox_inches='tight')
    plt.close(fig)

    # Designation and operator distributions
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    if 'designation' in df.columns:
        des = df['designation'].dropna().astype(str).str.strip()
        des = des[des != '']
        top_des = des.value_counts().head(12)
        ax[0].bar(top_des.index, top_des.values, color='tab:purple')
        ax[0].set_title('Top désignations (plateformes)')
        ax[0].tick_params(axis='x', labelrotation=45)
        ax[0].set_ylabel('Comptes')
    else:
        ax[0].text(0.5, 0.5, 'Pas de colonne designation', ha='center')

    org_col = None
    for c in df.columns:
        if 'BusinessOrganisationAbbreviation' in c:
            org_col = c; break
    if org_col:
        top_ops = df[org_col].astype(str).value_counts().head(12)
        ax[1].barh(top_ops.index[::-1], top_ops.values[::-1], color='tab:green')
        ax[1].set_title('Top organisations (abbr)')
    else:
        ax[1].text(0.5, 0.5, 'Pas de colonne opérateur', ha='center')
    fig.tight_layout(); fig.savefig(os.path.join(figdir, 'atlas_designation_operators.png'), bbox_inches='tight')
    plt.close(fig)

if __name__ == '__main__':
    main()


