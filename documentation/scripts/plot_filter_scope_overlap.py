#!/usr/bin/env python3
"""Generate a scope-overlap diagram for global stats filter dimensions.

Outputs:
- documentation/images/filter_scope_overlap_map.svg

Run (from repo root):
  python documentation/scripts/plot_filter_scope_overlap.py

Optional:
  python documentation/scripts/plot_filter_scope_overlap.py \
    --summary documentation/generated/filter_bucket_analysis.json
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUMMARY_PATH = ROOT / "documentation" / "generated" / "filter_bucket_analysis.json"
DEFAULT_OUTPUT_PATH = ROOT / "documentation" / "images" / "filter_scope_overlap_map.svg"


# Canonical project palette (documentation/6.7 Colours and styles.md)
COLOR_PRIMARY = "#174092"          # ATLAS matched / primary navy
COLOR_SUCCESS = "#4CAF50"          # OSM matched green
COLOR_DANGER = "#DC3545"           # ATLAS unmatched red
COLOR_SECONDARY = "#6C757D"        # OSM unmatched gray
COLOR_WARNING = "#F0AD4E"          # P2 orange
COLOR_INFO_BG = "#eef3fb"          # Primary subtle


def _format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "?"


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _dim_value(dims: dict[str, Any], key: str) -> str:
    value = dims.get(key)
    if value is None:
        return "?"
    try:
        return str(int(value))
    except Exception:
        return "?"


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: int = 14,
    color: str = "#111827",
    anchor: str = "start",
    weight: str | None = None,
) -> str:
    weight_attr = f' font-weight="{weight}"' if weight else ""
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" '
        f'font-family="Arial, sans-serif" fill="{color}"{weight_attr}>'
        f"{html.escape(content)}</text>"
    )


def _rounded_rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str,
    stroke: str,
    stroke_width: int = 2,
    radius: int = 10,
    dash: str | None = None,
) -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" ry="{radius}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"{dash_attr}/>'
    )


def _chip(
    svg: list[str],
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    sublabel: str,
    *,
    fill: str,
    stroke: str,
) -> None:
    svg.append(_rounded_rect(x, y, w, h, fill=fill, stroke=stroke, stroke_width=1, radius=8))
    svg.append(_text(x + w / 2, y + 30, label, size=15, anchor="middle", weight="bold"))
    svg.append(_text(x + w / 2, y + 52, sublabel, size=12, anchor="middle", color="#334155"))


def _safe_rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def build_svg(summary: dict[str, Any]) -> str:
    width = 1380
    height = 860

    scope_rows = summary.get("scope_rows", {})
    scope_dims = summary.get("scope_dimension_cardinality", {})
    transport = summary.get("transport_flag_overlap", {})

    ao_rows = scope_rows.get("atlas+osm", "?")
    a_rows = scope_rows.get("atlas_only", "?")
    o_rows = scope_rows.get("osm_only", "?")

    ao_dims = scope_dims.get("atlas+osm", {})
    a_dims = scope_dims.get("atlas_only", {})
    o_dims = scope_dims.get("osm_only", {})

    nodes_1 = transport.get("nodes_with_1_flag", "?")
    nodes_gt1 = transport.get("nodes_with_gt_1_flags", "?")
    total_nodes = transport.get("total_nodes", "?")

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _rounded_rect(28, 24, 1324, 742, fill="#f8fafc", stroke="#d1d5db", stroke_width=2, radius=8),
        _text(690, 58, "APPLICATION DATA UNIVERSE (stops_matched)", size=30, anchor="middle", weight="bold"),
    ]

    # Scope boxes (exclusive partition)
    svg.append(_rounded_rect(70, 110, 650, 440, fill="#e8f1ff", stroke=COLOR_PRIMARY, stroke_width=3, radius=14))
    svg.append(_rounded_rect(750, 110, 270, 440, fill="#fdecee", stroke=COLOR_DANGER, stroke_width=3, radius=14))
    svg.append(_rounded_rect(1050, 110, 260, 440, fill="#f3f4f6", stroke=COLOR_SECONDARY, stroke_width=3, radius=14))

    svg.append(
        _text(
            410,
            145,
            f"atlas+osm scope (rows: {_format_int(ao_rows)})",
            size=20,
            color=COLOR_PRIMARY,
            anchor="middle",
            weight="bold",
        )
    )
    svg.append(
        _text(
            885,
            145,
            f"atlas_only scope (rows: {_format_int(a_rows)})",
            size=16,
            color=COLOR_DANGER,
            anchor="middle",
            weight="bold",
        )
    )
    svg.append(
        _text(
            1180,
            145,
            f"osm_only scope (rows: {_format_int(o_rows)})",
            size=16,
            color=COLOR_SECONDARY,
            anchor="middle",
            weight="bold",
        )
    )

    # Dimension chips inside each scope
    _chip(
        svg,
        100,
        202,
        190,
        78,
        "atlas_operator",
        f"n={_dim_value(ao_dims, 'n_operator')}",
        fill=COLOR_INFO_BG,
        stroke=COLOR_PRIMARY,
    )
    _chip(
        svg,
        310,
        202,
        190,
        78,
        "transport_mask",
        f"n={_dim_value(ao_dims, 'n_transport_mask')}",
        fill="#edf7ed",
        stroke=COLOR_SUCCESS,
    )
    _chip(
        svg,
        100,
        326,
        190,
        78,
        "atlas_duplicate",
        f"n={_dim_value(ao_dims, 'n_duplicate')}",
        fill=COLOR_INFO_BG,
        stroke=COLOR_PRIMARY,
    )
    _chip(
        svg,
        310,
        326,
        190,
        78,
        "osm_group_kind",
        f"n={_dim_value(ao_dims, 'n_group_kind')}",
        fill="#edf7ed",
        stroke=COLOR_SUCCESS,
    )
    _chip(
        svg,
        205,
        450,
        190,
        78,
        "match_type",
        f"n={_dim_value(ao_dims, 'n_match_type')}",
        fill="#fff5e9",
        stroke=COLOR_WARNING,
    )

    _chip(
        svg,
        790,
        202,
        190,
        78,
        "atlas_operator",
        f"n={_dim_value(a_dims, 'n_operator')}",
        fill=COLOR_INFO_BG,
        stroke=COLOR_PRIMARY,
    )
    _chip(
        svg,
        790,
        326,
        190,
        78,
        "atlas_duplicate",
        f"n={_dim_value(a_dims, 'n_duplicate')}",
        fill=COLOR_INFO_BG,
        stroke=COLOR_PRIMARY,
    )
    _chip(
        svg,
        790,
        450,
        190,
        78,
        "match_type",
        f"n={_dim_value(a_dims, 'n_match_type')}",
        fill="#fff5e9",
        stroke=COLOR_WARNING,
    )

    _chip(
        svg,
        1085,
        202,
        150,
        78,
        "transport_mask",
        f"n={_dim_value(o_dims, 'n_transport_mask')}",
        fill="#edf7ed",
        stroke=COLOR_SUCCESS,
    )
    _chip(
        svg,
        1085,
        326,
        150,
        78,
        "osm_group_kind",
        f"n={_dim_value(o_dims, 'n_group_kind')}",
        fill="#edf7ed",
        stroke=COLOR_SUCCESS,
    )
    _chip(
        svg,
        1085,
        450,
        150,
        78,
        "match_type",
        f"n={_dim_value(o_dims, 'n_match_type')}",
        fill="#fff5e9",
        stroke=COLOR_WARNING,
    )

    # Dashed overlap guides by dimension family (kept separated to avoid visual collisions)
    svg.append(_rounded_rect(86, 170, 1194, 118, fill="none", stroke=COLOR_PRIMARY, stroke_width=2, radius=24, dash="8 6"))
    svg.append(
        _text(
            683,
            196,
            "top row dimensions (atlas_operator / transport_mask)",
            size=14,
            color=COLOR_PRIMARY,
            anchor="middle",
            weight="bold",
        )
    )

    svg.append(_rounded_rect(86, 292, 1194, 118, fill="none", stroke=COLOR_SUCCESS, stroke_width=2, radius=24, dash="8 6"))
    svg.append(
        _text(
            683,
            318,
            "middle row dimensions (atlas_duplicate / osm_group_kind)",
            size=14,
            color="#2f6f31",
            anchor="middle",
            weight="bold",
        )
    )

    svg.append(_rounded_rect(86, 416, 1194, 118, fill="none", stroke=COLOR_WARNING, stroke_width=2, radius=24, dash="8 6"))
    svg.append(
        _text(
            683,
            438,
            "match_type exists in all scopes, but allowed values depend on scope/stop_type",
            size=14,
            color="#9a6508",
            anchor="middle",
            weight="bold",
        )
    )

    # Cross-cutting request filters
    svg.append(_rounded_rect(70, 572, 1240, 128, fill=COLOR_INFO_BG, stroke=COLOR_PRIMARY, stroke_width=3, radius=12, dash="12 8"))
    svg.append(
        _text(
            690,
            612,
            "CROSS-CUTTING REQUEST FILTERS (intersect structural scopes)",
            size=20,
            color=COLOR_PRIMARY,
            anchor="middle",
            weight="bold",
        )
    )
    svg.append(
        _text(
            690,
            642,
            "smart search (sloid/node/uic/route), viewport bbox, and top_n (matched + distance only)",
            size=15,
            color=COLOR_PRIMARY,
            anchor="middle",
        )
    )
    svg.append(
        _text(
            690,
            668,
            "transport checkboxes are not exclusive and should be modeled as a 6-bit transport_mask",
            size=15,
            color=COLOR_PRIMARY,
            anchor="middle",
        )
    )

    svg.append(
        _text(
            690,
            724,
            (
                "Observed transport overlap in osm_nodes: "
                f"{_format_int(nodes_1)} with exactly 1 flag, "
                f"{_format_int(nodes_gt1)} with >1 flags "
                f"(total: {_format_int(total_nodes)})"
            ),
            size=14,
            color="#334155",
            anchor="middle",
        )
    )

    svg.append(_text(70, 795, "* Solid borders = exclusive row scopes (partition).", size=13, color="#374151"))
    svg.append(_text(70, 816, "* Dashed borders = overlapping dimensions that span multiple scopes.", size=13, color="#374151"))

    svg.append("</svg>")
    return "\n".join(svg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a scope-overlap diagram for global stats filters.")
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help=(
            "Path to filter_bucket_analysis.json "
            "(default: documentation/generated/filter_bucket_analysis.json)."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output SVG path (default: documentation/images/filter_scope_overlap_map.svg).",
    )
    args = parser.parse_args()

    summary = _load_summary(args.summary)
    svg = build_svg(summary)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")

    source = _safe_rel(args.summary) if summary else "(no summary file loaded)"
    print(f"Generated: {_safe_rel(args.output)}")
    print(f"Data source: {source}")


if __name__ == "__main__":
    main()
