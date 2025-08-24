#!/usr/bin/env python3
import os
import sys
from datetime import datetime
from pathlib import Path

import json
import pandas as pd
import sqlalchemy as sa
from sqlalchemy import text
import matplotlib
matplotlib.use('Agg')  # ensure headless backend
import matplotlib.pyplot as plt
import seaborn as sns


def get_engine():
    database_uri = os.getenv(
        'DATABASE_URI',
        'mysql+pymysql://stops_user:1234@localhost:3306/stops_db'
    )
    return sa.create_engine(database_uri, pool_pre_ping=True)


def ensure_output_dirs():
    figures_dir = Path(__file__).resolve().parents[2] / 'figures' / 'chap6'
    figures_dir.mkdir(parents=True, exist_ok=True)
    return figures_dir


def fetch_stats(engine: sa.Engine) -> dict:
    stats = {"generated_at": datetime.utcnow().isoformat() + "Z"}

    with engine.connect() as conn:
        # Total stops imported
        stats["total_stops"] = int(conn.execute(text("SELECT COUNT(*) FROM stops")).scalar())

        # Problem counts by type
        problems_by_type = conn.execute(text(
            """
            SELECT problem_type, COUNT(*) AS cnt
            FROM problems
            GROUP BY problem_type
            """
        )).fetchall()
        stats["problems_by_type"] = {row[0]: int(row[1]) for row in problems_by_type}

        # Distinct stops with any problems
        stats["stops_with_any_problem"] = int(conn.execute(text(
            "SELECT COUNT(DISTINCT stop_id) FROM problems"
        )).scalar())

        # Entries with multiple problems (per stop_id)
        stats["stops_with_multiple_problems"] = int(conn.execute(text(
            """
            SELECT COUNT(*) FROM (
              SELECT stop_id, COUNT(*) AS c
              FROM problems
              GROUP BY stop_id
              HAVING COUNT(*) > 1
            ) t
            """
        )).scalar())

        # Entries with no problems
        stats["stops_with_no_problems"] = int(conn.execute(text(
            """
            SELECT COUNT(*) FROM stops s
            WHERE NOT EXISTS (
              SELECT 1 FROM problems p WHERE p.stop_id = s.id
            )
            """
        )).scalar())

        # Priorities breakdown per type
        prio_rows = conn.execute(text(
            """
            SELECT problem_type, priority, COUNT(*) as cnt
            FROM problems
            WHERE priority IS NOT NULL
            GROUP BY problem_type, priority
            ORDER BY problem_type, priority
            """
        )).fetchall()
        stats["priority_by_type"] = {}
        for ptype, prio, cnt in prio_rows:
            stats["priority_by_type"].setdefault(ptype, {})[str(int(prio))] = int(cnt)

        # Distance metrics for distance problems
        dist_df = pd.read_sql(text(
            """
            SELECT s.distance_m
            FROM stops s
            JOIN problems p ON p.stop_id = s.id
            WHERE p.problem_type = 'distance' AND s.distance_m IS NOT NULL
            """
        ), conn)
        if not dist_df.empty:
            stats["distance_median"] = float(dist_df["distance_m"].median())
            stats["distance_p90"] = float(dist_df["distance_m"].quantile(0.90))
        else:
            stats["distance_median"] = None
            stats["distance_p90"] = None

        # Unmatched problems by side (ATLAS-only vs OSM-only)
        unmatched_by_side = conn.execute(text(
            """
            SELECT s.stop_type, COUNT(*) AS cnt
            FROM problems p
            JOIN stops s ON s.id = p.stop_id
            WHERE p.problem_type = 'unmatched'
            GROUP BY s.stop_type
            """
        )).fetchall()
        stats["unmatched_by_side"] = {str(row[0]): int(row[1]) for row in unmatched_by_side}

        # Operators most impacted by distance problems
        op_rows = conn.execute(text(
            """
            SELECT COALESCE(a.atlas_business_org_abbr, 'UNKNOWN') AS operator, COUNT(*) AS cnt
            FROM problems p
            JOIN stops s ON s.id = p.stop_id
            LEFT JOIN atlas_stops a ON a.sloid = s.sloid
            WHERE p.problem_type = 'distance'
            GROUP BY COALESCE(a.atlas_business_org_abbr, 'UNKNOWN')
            ORDER BY cnt DESC
            LIMIT 20
            """
        )).fetchall()
        stats["distance_by_operator_top"] = [{"operator": row[0], "count": int(row[1])} for row in op_rows]

        # Operators by percentage of entries with at least one P1 problem
        op_p1_rows = conn.execute(text(
            """
            WITH stops_with_op AS (
              SELECT s.id AS stop_id,
                     COALESCE(a.atlas_business_org_abbr, 'UNKNOWN') AS operator
              FROM stops s
              LEFT JOIN atlas_stops a ON a.sloid = s.sloid
            ),
            p1_stops AS (
              SELECT DISTINCT stop_id
              FROM problems
              WHERE priority = 1
            )
            SELECT swop.operator,
                   COUNT(*) AS total_stops,
                   SUM(CASE WHEN p1_stops.stop_id IS NOT NULL THEN 1 ELSE 0 END) AS p1_stops
            FROM stops_with_op swop
            LEFT JOIN p1_stops ON p1_stops.stop_id = swop.stop_id
            GROUP BY swop.operator
            """
        )).fetchall()
        stats["operators_p1_pct"] = [
            {
                "operator": row[0],
                "total": int(row[1]),
                "p1": int(row[2]),
                "pct": (float(row[2]) / float(row[1])) if row[1] else 0.0,
            }
            for row in op_p1_rows
        ]

        # Top 10 stations with most problems
        top_stops = conn.execute(text(
            """
            SELECT s.sloid,
                   COALESCE(a.atlas_designation_official, a.atlas_designation) AS name,
                   COUNT(DISTINCT p.problem_type) AS cnt
            FROM problems p
            JOIN stops s ON s.id = p.stop_id
            LEFT JOIN atlas_stops a ON a.sloid = s.sloid
            GROUP BY s.sloid, COALESCE(a.atlas_designation_official, a.atlas_designation)
            ORDER BY cnt DESC
            LIMIT 10
            """
        )).fetchall()
        stats["top_stops_by_problems"] = [
            {"sloid": row[0], "name": row[1], "count": int(row[2])} for row in top_stops
        ]

    return stats


def write_outputs(stats: dict, out_dir: Path):
    # JSON
    json_path = out_dir / 'problems_stats.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # Markdown summary
    md_path = out_dir / 'problems_stats.md'
    lines = []
    lines.append(f"# Problems Statistics (generated {stats['generated_at']})\n")
    lines.append(f"- Total stops: {stats.get('total_stops', 'NA')}\n")
    pbt = stats.get('problems_by_type', {})
    for k in sorted(pbt.keys()):
        lines.append(f"- {k}: {pbt[k]}\n")
    lines.append(f"- Stops with any problem: {stats.get('stops_with_any_problem', 'NA')}\n")
    lines.append(f"- Stops with multiple problems: {stats.get('stops_with_multiple_problems', 'NA')}\n")
    lines.append(f"- Stops with no problems: {stats.get('stops_with_no_problems', 'NA')}\n")
    if stats.get('distance_median') is not None:
        lines.append(f"- Distance median (for distance problems): {stats['distance_median']:.2f} m\n")
        lines.append(f"- Distance p90 (for distance problems): {stats['distance_p90']:.2f} m\n")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def generate_plots(engine: sa.Engine, stats: dict, out_dir: Path) -> None:
    sns.set_theme(style='whitegrid')

    # 1) Problems by type
    pbt = stats.get('problems_by_type', {})
    if pbt:
        plt.figure(figsize=(6, 4))
        keys = list(pbt.keys())
        vals = [pbt[k] for k in keys]
        ax = sns.barplot(x=keys, y=vals, palette='tab10')
        ax.set_title('Problems by type')
        ax.set_xlabel('Type')
        ax.set_ylabel('Count')
        plt.tight_layout()
        plt.savefig(out_dir / 'problems_by_type.png', dpi=150)
        plt.close()

    # 2) Priority by type (stacked)
    pr_by_type = stats.get('priority_by_type', {})
    if pr_by_type:
        # Create a DataFrame with index types and columns P1/P2/P3
        types = sorted(pr_by_type.keys())
        prios = ['1', '2', '3']
        data = []
        for t in types:
            row = [pr_by_type.get(t, {}).get(p, 0) for p in prios]
            data.append(row)
        df = pd.DataFrame(data, index=types, columns=[f'P{p}' for p in prios])
        plt.figure(figsize=(7, 4))
        bottom = None
        colors = sns.color_palette('tab10', n_colors=len(df.columns))
        for i, col in enumerate(df.columns):
            plt.bar(df.index, df[col], bottom=bottom, label=col, color=colors[i])
            bottom = (df[col] if bottom is None else bottom + df[col])
        plt.title('Priority distribution by problem type')
        plt.xlabel('Problem type')
        plt.ylabel('Count')
        plt.legend(title='Priority', bbox_to_anchor=(1.04, 1), loc='upper left')
        plt.tight_layout()
        plt.savefig(out_dir / 'priority_by_type.png', dpi=150)
        plt.close()

    # 3) Distance histogram for distance problems
    try:
        with engine.connect() as conn:
            dist_df = pd.read_sql(text(
                """
                SELECT s.distance_m
                FROM stops s
                JOIN problems p ON p.stop_id = s.id
                WHERE p.problem_type = 'distance' AND s.distance_m IS NOT NULL
                """
            ), conn)
        if not dist_df.empty:
            plt.figure(figsize=(7, 4))
            ax = sns.histplot(dist_df['distance_m'], bins=50, kde=False)
            ax.set_title('Distance distribution (distance problems)')
            ax.set_xlabel('Distance (m)')
            ax.set_ylabel('Count')
            plt.tight_layout()
            plt.savefig(out_dir / 'distance_hist.png', dpi=150)
            plt.close()
    except Exception:
        pass

    # 4) Unmatched by side
    unmatched = stats.get('unmatched_by_side', {})
    if unmatched:
        plt.figure(figsize=(5, 4))
        keys = list(unmatched.keys())
        vals = [unmatched[k] for k in keys]
        ax = sns.barplot(x=keys, y=vals, palette='pastel')
        ax.set_title('Unmatched by side')
        ax.set_xlabel('Side (ATLAS unmatched vs OSM only)')
        ax.set_ylabel('Count')
        plt.tight_layout()
        plt.savefig(out_dir / 'unmatched_by_side.png', dpi=150)
        plt.close()

    # 5) Top operators by distance problems
    ops = stats.get('distance_by_operator_top', [])
    if ops:
        ops_df = pd.DataFrame(ops)
        plt.figure(figsize=(7, 6))
        ops_top = ops_df.head(20)
        ax = sns.barplot(data=ops_top, y='operator', x='count', palette='Blues_r')
        ax.set_title('Top operators by distance problems')
        ax.set_xlabel('Count')
        ax.set_ylabel('Operator')
        plt.tight_layout()
        plt.savefig(out_dir / 'distance_by_operator_top.png', dpi=150)
        plt.close()

    # 6) Operators by percentage of entries with P1 problems
    op_p1 = stats.get('operators_p1_pct', [])
    if op_p1:
        df = pd.DataFrame(op_p1)
        # Optional: filter out tiny samples to reduce noise
        if 'total' in df.columns:
            df = df[df['total'] >= 30]
        if not df.empty:
            df = df.sort_values('pct', ascending=False).head(15)
            plt.figure(figsize=(8, 6))
            ax = sns.barplot(data=df, y='operator', x=(df['pct'] * 100.0), palette='Reds_r')
            ax.set_title('Operators with highest % of entries with P1 problems')
            ax.set_xlabel('% of entries with P1 problems')
            ax.set_ylabel('Operator')
            plt.tight_layout()
            plt.savefig(out_dir / 'operators_p1_percentage.png', dpi=150)
            plt.close()


def main():
    out_dir = ensure_output_dirs()
    try:
        engine = get_engine()
        stats = fetch_stats(engine)
        write_outputs(stats, out_dir)
        generate_plots(engine, stats, out_dir)
        print(f"Wrote stats to {out_dir}")
    except Exception as e:
        # Fail gracefully but return non-zero to signal failure when used in CI
        err_path = out_dir / 'problems_stats_error.txt'
        with open(err_path, 'w', encoding='utf-8') as f:
            f.write(f"Error generating stats: {e}\n")
        print(f"Error generating stats: {e}", file=sys.stderr)
        raise


if __name__ == '__main__':
    main()


