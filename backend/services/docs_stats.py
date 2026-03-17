"""Shared helpers for loading and rendering documentation stats placeholders."""

from __future__ import annotations

import json
import os
import re
from html import escape
from typing import Any, Optional


_STATS_PATTERN = re.compile(r'\{\{stat:([a-zA-Z0-9_.]+)\}\}')


def load_stats_for_docs() -> Optional[dict]:
    """Load unified stats from data/stats.json."""
    try:
        stats_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data',
            'stats.json',
        )
        if os.path.exists(stats_file_path):
            with open(stats_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        return None
    return None


def get_nested_stat_value(stats: Optional[dict], key_path: str) -> Any:
    """Get nested dict value via dot notation (example: summary.match_rate_percent)."""
    if not stats:
        return None

    value: Any = stats
    for key in key_path.split('.'):
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def format_stat_value(value: Any) -> str:
    """Format a stats value for docs display."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        if 0 < value < 1:
            return f"{value:.1%}"
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def replace_stats_placeholders(content: str, stats: Optional[dict] = None, *, html_escape: bool = False) -> str:
    """Replace {{stat:key.path}} placeholders with formatted values.

    html_escape=True is useful for static document generation where placeholder
    values should be escaped explicitly.
    """
    if stats is None:
        stats = load_stats_for_docs()

    def replace(match: re.Match[str]) -> str:
        key_path = match.group(1)
        value = get_nested_stat_value(stats, key_path)
        formatted = format_stat_value(value)

        css_class = 'dynamic-stat'
        if value is None:
            css_class += ' stat-unavailable'

        if html_escape:
            key_path_text = escape(key_path)
            formatted_text = escape(formatted)
        else:
            key_path_text = key_path
            formatted_text = formatted

        return (
            f'<span class="{css_class}" data-stat-key="{key_path_text}" '
            f'title="Auto-updated from pipeline stats">{formatted_text}</span>'
        )

    return _STATS_PATTERN.sub(replace, content)
