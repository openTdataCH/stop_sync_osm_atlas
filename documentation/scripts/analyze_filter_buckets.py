#!/usr/bin/env python3
"""Analyze filter bucket math and generate documentation artifacts.

Outputs:
- documentation/generated/filter_bucket_analysis.json
- documentation/images/filter_bucket_populated_by_scope.svg
- documentation/images/filter_bucket_sparsity_log.svg
- documentation/images/filter_bucket_applicability_matrix.svg

Run (from repo root):
  docker exec stop_sync_osm_atlas_app python documentation/scripts/analyze_filter_buckets.py
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = ROOT / "documentation" / "images"
GENERATED_DIR = ROOT / "documentation" / "generated"
SUMMARY_PATH = GENERATED_DIR / "filter_bucket_analysis.json"


SQL_OPERATOR_COUNTS = """
SELECT
    COUNT(DISTINCT atlas_business_org_abbr) FILTER (
        WHERE atlas_business_org_abbr IS NOT NULL AND atlas_business_org_abbr <> ''
    ) AS operator_non_empty,
    COUNT(DISTINCT NULLIF(TRIM(atlas_business_org_abbr), '')) AS operator_trimmed_non_empty,
    COUNT(*) FILTER (WHERE atlas_business_org_abbr IS NULL OR atlas_business_org_abbr = '') AS blank_operator_rows
FROM atlas_stops
"""

SQL_STOP_TYPES = """
SELECT stop_type, COUNT(*) AS rows
FROM stops_matched
GROUP BY stop_type
ORDER BY rows DESC
"""

SQL_MATCH_TYPES_BY_STOP = """
SELECT
    stop_type,
    COALESCE(match_type, '<NULL>') AS match_type,
    COUNT(*) AS rows
FROM stops_matched
GROUP BY stop_type, COALESCE(match_type, '<NULL>')
ORDER BY stop_type, rows DESC
"""

SQL_TRANSPORT_FLAG_OVERLAP = """
WITH f AS (
    SELECT
        CASE WHEN osm_amenity = 'ferry_terminal' THEN 1 ELSE 0 END AS ferry,
        CASE WHEN osm_railway = 'tram_stop' THEN 1 ELSE 0 END AS tram,
        CASE WHEN osm_node_type = 'railway_station' THEN 1 ELSE 0 END AS station,
        CASE WHEN osm_public_transport = 'platform' THEN 1 ELSE 0 END AS platform,
        CASE WHEN osm_public_transport = 'stop_position' THEN 1 ELSE 0 END AS stop_position,
        CASE WHEN osm_aerialway = 'station' THEN 1 ELSE 0 END AS aerialway
    FROM osm_nodes
),
s AS (
    SELECT (ferry + tram + station + platform + stop_position + aerialway) AS active_flags
    FROM f
)
SELECT
    COUNT(*) AS total_nodes,
    COUNT(*) FILTER (WHERE active_flags = 0) AS nodes_with_0_flags,
    COUNT(*) FILTER (WHERE active_flags = 1) AS nodes_with_1_flag,
    COUNT(*) FILTER (WHERE active_flags > 1) AS nodes_with_gt_1_flags
FROM s
"""

SQL_TRANSPORT_MASK_TOP = """
WITH f AS (
    SELECT
        CONCAT(
            CASE WHEN osm_amenity = 'ferry_terminal' THEN '1' ELSE '0' END,
            CASE WHEN osm_railway = 'tram_stop' THEN '1' ELSE '0' END,
            CASE WHEN osm_node_type = 'railway_station' THEN '1' ELSE '0' END,
            CASE WHEN osm_public_transport = 'platform' THEN '1' ELSE '0' END,
            CASE WHEN osm_public_transport = 'stop_position' THEN '1' ELSE '0' END,
            CASE WHEN osm_aerialway = 'station' THEN '1' ELSE '0' END
        ) AS transport_mask
    FROM osm_nodes
)
SELECT transport_mask, COUNT(*) AS nodes
FROM f
GROUP BY transport_mask
ORDER BY nodes DESC, transport_mask
LIMIT 16
"""

SQL_SCOPE_DIMENSIONS = """
WITH sibling AS (
    SELECT representative_sloid
    FROM atlas_stops
    WHERE representative_sloid IS NOT NULL
),
group_map AS (
    SELECT
        m.node_id,
        COALESCE(NULLIF(s.group_kind, ''), 'single') AS group_kind
    FROM osm_stop_members m
    JOIN osm_stops s ON s.id = m.osm_stop_id
),
dim AS (
    SELECT
        CASE
            WHEN sm.sloid IS NOT NULL AND sm.osm_node_id IS NOT NULL THEN 'atlas+osm'
            WHEN sm.sloid IS NOT NULL THEN 'atlas_only'
            WHEN sm.osm_node_id IS NOT NULL THEN 'osm_only'
            ELSE 'none'
        END AS scope,
        COALESCE(NULLIF(TRIM(a.atlas_business_org_abbr), ''), '<NO_ATLAS_OPERATOR>') AS atlas_operator,
        CASE
            WHEN sm.sloid IS NULL THEN '<NA>'
            WHEN a.representative_sloid IS NOT NULL
              OR sm.sloid IN (SELECT representative_sloid FROM sibling) THEN 'duplicate'
            ELSE 'not_duplicate'
        END AS atlas_duplicate,
        CASE
            WHEN sm.osm_node_id IS NULL THEN '<NA>'
            ELSE CONCAT(
                CASE WHEN o.osm_amenity = 'ferry_terminal' THEN '1' ELSE '0' END,
                CASE WHEN o.osm_railway = 'tram_stop' THEN '1' ELSE '0' END,
                CASE WHEN o.osm_node_type = 'railway_station' THEN '1' ELSE '0' END,
                CASE WHEN o.osm_public_transport = 'platform' THEN '1' ELSE '0' END,
                CASE WHEN o.osm_public_transport = 'stop_position' THEN '1' ELSE '0' END,
                CASE WHEN o.osm_aerialway = 'station' THEN '1' ELSE '0' END
            )
        END AS transport_mask,
        CASE
            WHEN sm.osm_node_id IS NULL THEN '<NA>'
            ELSE COALESCE(g.group_kind, 'no_membership')
        END AS osm_group_kind,
        COALESCE(sm.match_type, '<NULL>') AS match_type
    FROM stops_matched sm
    LEFT JOIN atlas_stops a ON a.sloid = sm.sloid
    LEFT JOIN osm_nodes o ON o.osm_node_id = sm.osm_node_id
    LEFT JOIN group_map g ON g.node_id = sm.osm_node_id
)
SELECT
    scope,
    COUNT(*) AS scope_rows,
    COUNT(DISTINCT atlas_operator) FILTER (WHERE atlas_operator <> '<NA>') AS n_operator,
    COUNT(DISTINCT atlas_duplicate) FILTER (WHERE atlas_duplicate <> '<NA>') AS n_duplicate,
    COUNT(DISTINCT transport_mask) FILTER (WHERE transport_mask <> '<NA>') AS n_transport_mask,
    COUNT(DISTINCT osm_group_kind) FILTER (WHERE osm_group_kind <> '<NA>') AS n_group_kind,
    COUNT(DISTINCT match_type) AS n_match_type,
    COUNT(DISTINCT (atlas_operator, atlas_duplicate, transport_mask, osm_group_kind, match_type)) AS populated_buckets
FROM dim
WHERE scope <> 'none'
GROUP BY scope
ORDER BY scope
"""


def _format_int(n: int) -> str:
    return f"{int(n):,}"


def _get_connection_kwargs() -> dict:
    uri = os.getenv("DATABASE_URI")
    if uri:
        normalized = uri.replace("postgresql+psycopg://", "postgresql://", 1)
        parsed = urlparse(normalized)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "dbname": (parsed.path or "/import_db").lstrip("/"),
            "user": unquote(parsed.username or "stops_user"),
            "password": unquote(parsed.password or "1234"),
        }

    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "import_db"),
        "user": os.getenv("DB_USER", "stops_user"),
        "password": os.getenv("DB_PASSWORD", "1234"),
    }


def _fetch_all(conn: psycopg.Connection, sql: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return cur.fetchall()


def _scope_theoretical_max(scope: str, row: dict) -> int:
    if scope == "atlas+osm":
        return (
            int(row["n_operator"])
            * int(row["n_duplicate"])
            * int(row["n_transport_mask"])
            * int(row["n_group_kind"])
            * int(row["n_match_type"])
        )
    if scope == "atlas_only":
        return int(row["n_operator"]) * int(row["n_duplicate"]) * int(row["n_match_type"])
    if scope == "osm_only":
        return int(row["n_transport_mask"]) * int(row["n_group_kind"]) * int(row["n_match_type"])
    return 0


def _write_svg_bar_chart(path: Path, values: dict[str, int], title: str) -> None:
    width = 980
    height = 520
    margin_left = 110
    margin_right = 40
    margin_top = 90
    margin_bottom = 90
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    labels = list(values.keys())
    max_val = max(values.values()) if values else 1
    max_val = max(max_val, 1)

    bar_gap = 28
    bar_w = int((plot_w - bar_gap * (len(labels) - 1)) / max(len(labels), 1))

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin_left}" y="42" font-size="28" font-family="Arial, sans-serif" fill="#1f2937">{title}</text>',
        f'<text x="{margin_left}" y="68" font-size="15" font-family="Arial, sans-serif" fill="#4b5563">Distinct populated composite keys from stops_matched</text>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="#111827" stroke-width="1.5"/>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="#111827" stroke-width="1.5"/>',
    ]

    tick_count = 5
    for i in range(tick_count + 1):
        y = margin_top + plot_h - (plot_h * i / tick_count)
        tick_val = int(max_val * i / tick_count)
        svg_lines.append(
            f'<line x1="{margin_left - 6}" y1="{y:.2f}" x2="{margin_left}" y2="{y:.2f}" stroke="#374151" stroke-width="1"/>'
        )
        svg_lines.append(
            f'<text x="{margin_left - 12}" y="{y + 5:.2f}" text-anchor="end" font-size="12" font-family="Arial, sans-serif" fill="#4b5563">{_format_int(tick_val)}</text>'
        )
        if i > 0:
            svg_lines.append(
                f'<line x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_w}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1"/>'
            )

    for idx, label in enumerate(labels):
        value = values[label]
        h = (value / max_val) * plot_h
        x = margin_left + idx * (bar_w + bar_gap)
        y = margin_top + plot_h - h

        svg_lines.append(
            f'<rect x="{x}" y="{y:.2f}" width="{bar_w}" height="{h:.2f}" fill="#0ea5e9" opacity="0.9"/>'
        )
        svg_lines.append(
            f'<text x="{x + bar_w / 2:.2f}" y="{y - 10:.2f}" text-anchor="middle" font-size="13" font-family="Arial, sans-serif" fill="#111827">{_format_int(value)}</text>'
        )
        svg_lines.append(
            f'<text x="{x + bar_w / 2:.2f}" y="{margin_top + plot_h + 24}" text-anchor="middle" font-size="14" font-family="Arial, sans-serif" fill="#111827">{label}</text>'
        )

    svg_lines.append('</svg>')
    path.write_text("\n".join(svg_lines), encoding="utf-8")


def _write_svg_log_comparison(path: Path, populated: dict[str, int], theoretical: dict[str, int]) -> None:
    width = 1080
    height = 560
    margin_left = 120
    margin_right = 40
    margin_top = 100
    margin_bottom = 110
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    scopes = ["atlas+osm", "atlas_only", "osm_only"]
    max_val = max(max(theoretical.values(), default=1), max(populated.values(), default=1), 1)
    max_log = math.log10(max_val + 1)

    group_gap = 52
    pair_width = int((plot_w - group_gap * (len(scopes) - 1)) / max(len(scopes), 1))
    bar_w = max(20, int(pair_width * 0.35))

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin_left}" y="42" font-size="27" font-family="Arial, sans-serif" fill="#1f2937">Scope Theoretical Max vs Populated (log10 scale)</text>',
        f'<text x="{margin_left}" y="68" font-size="15" font-family="Arial, sans-serif" fill="#4b5563">Theoretical uses observed per-scope cardinalities multiplied together</text>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="#111827" stroke-width="1.5"/>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="#111827" stroke-width="1.5"/>',
    ]

    tick_values = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000]
    tick_values = [v for v in tick_values if v <= max_val]
    if 1 not in tick_values:
        tick_values = [1] + tick_values

    for tick in tick_values:
        y = margin_top + plot_h - (math.log10(tick + 1) / max_log) * plot_h
        svg_lines.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_w}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1"/>'
        )
        svg_lines.append(
            f'<text x="{margin_left - 12}" y="{y + 5:.2f}" text-anchor="end" font-size="12" font-family="Arial, sans-serif" fill="#4b5563">{_format_int(tick)}</text>'
        )

    for idx, scope in enumerate(scopes):
        x0 = margin_left + idx * (pair_width + group_gap)
        theo = theoretical.get(scope, 0)
        pop = populated.get(scope, 0)

        theo_h = (math.log10(theo + 1) / max_log) * plot_h if theo > 0 else 0
        pop_h = (math.log10(pop + 1) / max_log) * plot_h if pop > 0 else 0

        x_theo = x0 + int(pair_width * 0.12)
        x_pop = x_theo + bar_w + int(pair_width * 0.14)

        y_theo = margin_top + plot_h - theo_h
        y_pop = margin_top + plot_h - pop_h

        svg_lines.append(
            f'<rect x="{x_theo}" y="{y_theo:.2f}" width="{bar_w}" height="{theo_h:.2f}" fill="#64748b"/>'
        )
        svg_lines.append(
            f'<rect x="{x_pop}" y="{y_pop:.2f}" width="{bar_w}" height="{pop_h:.2f}" fill="#06b6d4"/>'
        )

        svg_lines.append(
            f'<text x="{x_theo + bar_w / 2:.2f}" y="{y_theo - 8:.2f}" text-anchor="middle" font-size="12" font-family="Arial, sans-serif" fill="#111827">{_format_int(theo)}</text>'
        )
        svg_lines.append(
            f'<text x="{x_pop + bar_w / 2:.2f}" y="{y_pop - 8:.2f}" text-anchor="middle" font-size="12" font-family="Arial, sans-serif" fill="#111827">{_format_int(pop)}</text>'
        )

        svg_lines.append(
            f'<text x="{x0 + pair_width / 2:.2f}" y="{margin_top + plot_h + 28}" text-anchor="middle" font-size="14" font-family="Arial, sans-serif" fill="#111827">{scope}</text>'
        )

    legend_x = margin_left
    legend_y = height - 42
    svg_lines.append(
        f'<rect x="{legend_x}" y="{legend_y - 12}" width="16" height="16" fill="#64748b"/><text x="{legend_x + 24}" y="{legend_y}" font-size="13" font-family="Arial, sans-serif" fill="#111827">Theoretical max</text>'
    )
    svg_lines.append(
        f'<rect x="{legend_x + 190}" y="{legend_y - 12}" width="16" height="16" fill="#06b6d4"/><text x="{legend_x + 214}" y="{legend_y}" font-size="13" font-family="Arial, sans-serif" fill="#111827">Populated buckets</text>'
    )

    svg_lines.append('</svg>')
    path.write_text("\n".join(svg_lines), encoding="utf-8")


def _write_svg_applicability_matrix(path: Path) -> None:
    width = 980
    height = 420
    margin_left = 220
    margin_top = 100
    cell_w = 140
    cell_h = 64

    rows = ["atlas+osm", "atlas_only", "osm_only"]
    cols = [
        "atlas_operator",
        "atlas_duplicate",
        "transport_mask",
        "osm_group_kind",
        "match_type",
    ]

    matrix = {
        "atlas+osm": [True, True, True, True, True],
        "atlas_only": [True, True, False, False, True],
        "osm_only": [False, False, True, True, True],
    }

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="48" y="42" font-size="27" font-family="Arial, sans-serif" fill="#1f2937">Dimension Applicability by Scope</text>',
        '<text x="48" y="68" font-size="15" font-family="Arial, sans-serif" fill="#4b5563">Green means the dimension exists for that scope; gray means N/A</text>',
    ]

    for c_idx, col in enumerate(cols):
        x = margin_left + c_idx * cell_w + cell_w / 2
        svg_lines.append(
            f'<text x="{x:.2f}" y="{margin_top - 16}" text-anchor="middle" font-size="12" font-family="Arial, sans-serif" fill="#111827">{col}</text>'
        )

    for r_idx, row in enumerate(rows):
        y = margin_top + r_idx * cell_h
        svg_lines.append(
            f'<text x="{margin_left - 16}" y="{y + cell_h / 2 + 5:.2f}" text-anchor="end" font-size="14" font-family="Arial, sans-serif" fill="#111827">{row}</text>'
        )
        for c_idx, col in enumerate(cols):
            x = margin_left + c_idx * cell_w
            applicable = matrix[row][c_idx]
            fill = "#10b981" if applicable else "#d1d5db"
            text = "yes" if applicable else "N/A"
            text_fill = "#052e16" if applicable else "#374151"
            svg_lines.append(
                f'<rect x="{x}" y="{y}" width="{cell_w - 6}" height="{cell_h - 6}" rx="8" ry="8" fill="{fill}"/>'
            )
            svg_lines.append(
                f'<text x="{x + (cell_w - 6) / 2:.2f}" y="{y + (cell_h - 6) / 2 + 5:.2f}" text-anchor="middle" font-size="16" font-family="Arial, sans-serif" fill="{text_fill}">{text}</text>'
            )

    svg_lines.append('</svg>')
    path.write_text("\n".join(svg_lines), encoding="utf-8")


def main() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    conn_kwargs = _get_connection_kwargs()

    with psycopg.connect(**conn_kwargs) as conn:
        operator_counts = _fetch_all(conn, SQL_OPERATOR_COUNTS)[0]
        stop_types = _fetch_all(conn, SQL_STOP_TYPES)
        match_types_by_stop = _fetch_all(conn, SQL_MATCH_TYPES_BY_STOP)
        transport_flag_overlap = _fetch_all(conn, SQL_TRANSPORT_FLAG_OVERLAP)[0]
        transport_mask_top = _fetch_all(conn, SQL_TRANSPORT_MASK_TOP)
        scope_dimensions = _fetch_all(conn, SQL_SCOPE_DIMENSIONS)

    scope_populated = {}
    scope_theoretical = {}
    scope_rows = {}
    scope_dimension_cardinality = {}

    for row in scope_dimensions:
        scope = row["scope"]
        scope_rows[scope] = int(row["scope_rows"])
        scope_populated[scope] = int(row["populated_buckets"])
        scope_dimension_cardinality[scope] = {
            "n_operator": int(row["n_operator"]),
            "n_duplicate": int(row["n_duplicate"]),
            "n_transport_mask": int(row["n_transport_mask"]),
            "n_group_kind": int(row["n_group_kind"]),
            "n_match_type": int(row["n_match_type"]),
        }
        scope_theoretical[scope] = _scope_theoretical_max(scope, row)

    total_populated = sum(scope_populated.values())
    total_theoretical = sum(scope_theoretical.values())
    sparsity_ratio = (total_populated / total_theoretical) if total_theoretical else 0.0

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_connection": {
            "host": conn_kwargs.get("host"),
            "port": conn_kwargs.get("port"),
            "dbname": conn_kwargs.get("dbname"),
        },
        "atlas_operator_counts": {
            "operator_non_empty_distinct": int(operator_counts["operator_non_empty"]),
            "operator_trimmed_non_empty_distinct": int(operator_counts["operator_trimmed_non_empty"]),
            "blank_operator_rows": int(operator_counts["blank_operator_rows"]),
        },
        "stop_type_rows": {row["stop_type"]: int(row["rows"]) for row in stop_types},
        "match_type_by_stop_type": [
            {
                "stop_type": row["stop_type"],
                "match_type": row["match_type"],
                "rows": int(row["rows"]),
            }
            for row in match_types_by_stop
        ],
        "transport_flag_overlap": {
            "total_nodes": int(transport_flag_overlap["total_nodes"]),
            "nodes_with_0_flags": int(transport_flag_overlap["nodes_with_0_flags"]),
            "nodes_with_1_flag": int(transport_flag_overlap["nodes_with_1_flag"]),
            "nodes_with_gt_1_flags": int(transport_flag_overlap["nodes_with_gt_1_flags"]),
        },
        "transport_mask_top": [
            {"transport_mask": row["transport_mask"], "nodes": int(row["nodes"])}
            for row in transport_mask_top
        ],
        "scope_rows": scope_rows,
        "scope_dimension_cardinality": scope_dimension_cardinality,
        "scope_populated_buckets": scope_populated,
        "scope_theoretical_max_buckets": scope_theoretical,
        "total_populated_buckets": total_populated,
        "total_theoretical_max_buckets": total_theoretical,
        "sparsity_ratio": sparsity_ratio,
    }

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    _write_svg_bar_chart(
        IMAGES_DIR / "filter_bucket_populated_by_scope.svg",
        {
            "atlas+osm": scope_populated.get("atlas+osm", 0),
            "atlas_only": scope_populated.get("atlas_only", 0),
            "osm_only": scope_populated.get("osm_only", 0),
        },
        "Populated Buckets by Scope",
    )

    _write_svg_log_comparison(
        IMAGES_DIR / "filter_bucket_sparsity_log.svg",
        populated={
            "atlas+osm": scope_populated.get("atlas+osm", 0),
            "atlas_only": scope_populated.get("atlas_only", 0),
            "osm_only": scope_populated.get("osm_only", 0),
        },
        theoretical={
            "atlas+osm": scope_theoretical.get("atlas+osm", 0),
            "atlas_only": scope_theoretical.get("atlas_only", 0),
            "osm_only": scope_theoretical.get("osm_only", 0),
        },
    )

    _write_svg_applicability_matrix(IMAGES_DIR / "filter_bucket_applicability_matrix.svg")

    print("Generated:")
    print(f"- {SUMMARY_PATH.relative_to(ROOT)}")
    print(f"- {(IMAGES_DIR / 'filter_bucket_populated_by_scope.svg').relative_to(ROOT)}")
    print(f"- {(IMAGES_DIR / 'filter_bucket_sparsity_log.svg').relative_to(ROOT)}")
    print(f"- {(IMAGES_DIR / 'filter_bucket_applicability_matrix.svg').relative_to(ROOT)}")
    print(f"Populated buckets: {_format_int(total_populated)}")
    print(f"Theoretical max (scope-aware): {_format_int(total_theoretical)}")
    print(f"Occupancy ratio: {sparsity_ratio:.4%}")


if __name__ == "__main__":
    main()
