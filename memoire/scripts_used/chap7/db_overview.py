#!/usr/bin/env python3
import os
import sys
from datetime import datetime

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import text

import matplotlib
matplotlib.use('Agg')  # headless
import matplotlib.pyplot as plt
import seaborn as sns


def get_engine():
    uri = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
    return sa.create_engine(uri)


def ensure_output_dirs():
    fig_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../figures/chap7'))
    os.makedirs(fig_dir, exist_ok=True)
    return fig_dir


def read_counts(engine):
    with engine.connect() as conn:
        total_stops = conn.execute(text("SELECT COUNT(*) FROM stops")).scalar()
        matched = conn.execute(text("SELECT COUNT(*) FROM stops WHERE stop_type='matched'")) .scalar()
        unmatched = conn.execute(text("SELECT COUNT(*) FROM stops WHERE stop_type='unmatched'")) .scalar()
        osm_only = conn.execute(text("SELECT COUNT(*) FROM stops WHERE stop_type='osm'")) .scalar()

        # Problems breakdown
        problems_df = pd.read_sql(text(
            """
            SELECT problem_type,
                   SUM(CASE WHEN solution IS NOT NULL AND solution <> '' THEN 1 ELSE 0 END) AS solved,
                   SUM(CASE WHEN solution IS NULL OR solution = '' THEN 1 ELSE 0 END) AS unsolved,
                   COUNT(*) AS total
            FROM problems
            GROUP BY problem_type
            """
        ), conn)

        # Routes breakdown
        routes_df = pd.read_sql(text(
            """
            SELECT match_type, source, COUNT(*) AS cnt
            FROM routes_and_directions
            GROUP BY match_type, source
            """
        ), conn)

        # Distances for matched only
        distances_df = pd.read_sql(text(
            """
            SELECT distance_m
            FROM stops
            WHERE stop_type='matched' AND distance_m IS NOT NULL
            """
        ), conn)

    return {
        'totals': {'stops': total_stops, 'matched': matched, 'unmatched': unmatched, 'osm_only': osm_only},
        'problems': problems_df,
        'routes': routes_df,
        'distances': distances_df,
    }


def plot_counts(totals, fig_dir):
    data = pd.DataFrame([
        {'type': 'matched', 'count': totals['matched']},
        {'type': 'unmatched (ATLAS)', 'count': totals['unmatched']},
        {'type': 'osm', 'count': totals['osm_only']},
    ])
    plt.figure(figsize=(7, 4))
    ax = sns.barplot(data=data, x='type', y='count', palette='Set2')
    for p in ax.patches:
        ax.annotate(f"{int(p.get_height())}", (p.get_x() + p.get_width()/2., p.get_height()),
                    ha='center', va='bottom', fontsize=9, xytext=(0, 3), textcoords='offset points')
    plt.title('Répartition des entrées par type')
    plt.xlabel('Type de stop')
    plt.ylabel('Nombre d\'entrées')
    out = os.path.join(fig_dir, 'stops_by_type.png')
    plt.tight_layout()
    plt.savefig(out, dpi=160)
    plt.close()
    return out


def plot_distances(distances_df, fig_dir):
    if distances_df.empty:
        return None
    # Cap at 200m for a focused view and add full view
    plt.figure(figsize=(7, 4))
    clipped = distances_df.copy()
    clipped = clipped[clipped['distance_m'].between(0, 200)]
    if not clipped.empty:
        sns.histplot(clipped['distance_m'], bins=40, kde=False, color='#4C78A8')
    plt.title('Distances Atlas ↔ OSM (0–200 m)')
    plt.xlabel('Distance (m)')
    plt.ylabel('Fréquence')
    out1 = os.path.join(fig_dir, 'distances_hist_0_200.png')
    plt.tight_layout(); plt.savefig(out1, dpi=160); plt.close()

    plt.figure(figsize=(7, 4))
    sns.histplot(distances_df['distance_m'], bins=60, kde=False, color='#72B7B2')
    plt.title('Distances Atlas ↔ OSM (toutes)')
    plt.xlabel('Distance (m)')
    plt.ylabel('Fréquence')
    out2 = os.path.join(fig_dir, 'distances_hist_all.png')
    plt.tight_layout(); plt.savefig(out2, dpi=160); plt.close()
    return out1, out2


def plot_problems(problems_df, fig_dir):
    if problems_df.empty:
        return None
    long_df = problems_df.melt(id_vars=['problem_type', 'total'], value_vars=['solved', 'unsolved'],
                               var_name='status', value_name='count')
    plt.figure(figsize=(8, 4))
    ax = sns.barplot(data=long_df, x='problem_type', y='count', hue='status', palette='Set1')
    plt.title('Problèmes: résolus vs non résolus')
    plt.xlabel('Type de problème')
    plt.ylabel('Nombre')
    for c in ax.containers:
        ax.bar_label(c, fmt='%d', padding=2, fontsize=8)
    out = os.path.join(fig_dir, 'problems_breakdown.png')
    plt.tight_layout(); plt.savefig(out, dpi=160); plt.close()
    return out


def plot_routes(routes_df, fig_dir):
    if routes_df.empty:
        return None
    plt.figure(figsize=(8, 4))
    ax = sns.barplot(data=routes_df, x='match_type', y='cnt', hue='source', palette='Paired')
    plt.title('Routes et directions par type de correspondance')
    plt.xlabel('Type de correspondance (match_type)')
    plt.ylabel('Nombre de lignes (rows)')
    ax.tick_params(axis='x', rotation=30)
    out = os.path.join(fig_dir, 'routes_match_breakdown.png')
    plt.tight_layout(); plt.savefig(out, dpi=160); plt.close()
    return out


def main():
    fig_dir = ensure_output_dirs()
    print('Figures will be stored in:', fig_dir)
    engine = get_engine()
    stats = read_counts(engine)
    print('Totals:', stats['totals'])
    paths = {}
    p1 = plot_counts(stats['totals'], fig_dir)
    if p1: paths['stops_by_type'] = os.path.basename(p1)
    p2 = plot_distances(stats['distances'], fig_dir)
    if p2:
        paths['distances_hist_0_200'] = os.path.basename(p2[0])
        paths['distances_hist_all'] = os.path.basename(p2[1])
    p3 = plot_problems(stats['problems'], fig_dir)
    if p3: paths['problems_breakdown'] = os.path.basename(p3)
    p4 = plot_routes(stats['routes'], fig_dir)
    if p4: paths['routes_match_breakdown'] = os.path.basename(p4)

    # Save a small metadata JSON for LaTeX or later inspection
    meta = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'paths': paths,
        'totals': stats['totals'],
    }
    meta_path = os.path.join(fig_dir, 'chap7_meta.json')
    pd.Series(meta).to_json(meta_path)
    print('Generated files:', meta)


if __name__ == '__main__':
    sys.exit(main())


