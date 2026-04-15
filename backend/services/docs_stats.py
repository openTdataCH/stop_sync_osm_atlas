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


def replace_stats_placeholders(content: str, stats: Optional[dict] = None, *, html_escape: bool = False, no_span: bool = False) -> str:
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

        if no_span:
            if html_escape:
                return escape(formatted)
            return formatted

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


def convert_github_alerts_to_html(markdown_text: str) -> str:
    """
    Convert GitHub-style alerts/admonitions to styled HTML.
    
    Handles patterns like:
    > [!NOTE]
    > Content here
    """
    alert_types = {
        'NOTE': ('info-circle', 'alert-note'),
        'TIP': ('lightbulb', 'alert-tip'),
        'IMPORTANT': ('exclamation-circle', 'alert-important'),
        'WARNING': ('exclamation-triangle', 'alert-warning'),
        'CAUTION': ('radiation', 'alert-caution'),
    }
    
    def replace_alert(match: re.Match[str]) -> str:
        alert_type = match.group(1).upper()
        content = match.group(2)
        
        if alert_type not in alert_types:
            return match.group(0)
        
        icon, css_class = alert_types[alert_type]
        
        lines = content.strip().split('\n')
        cleaned_lines = []
        for line in lines:
            if line.startswith('> '):
                cleaned_lines.append(line[2:])
            elif line.startswith('>'):
                cleaned_lines.append(line[1:])
            else:
                cleaned_lines.append(line)
        
        cleaned_content = '\n'.join(cleaned_lines).strip()
        
        return f'''<div class="github-alert {css_class}">
<div class="alert-title"><i class="fas fa-{icon}"></i> {alert_type.title()}</div>
<div class="alert-content">

{cleaned_content}

</div>
</div>

'''
    
    pattern = r'>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\n((?:>.*(?:\n|$))+)'
    return re.sub(pattern, replace_alert, markdown_text, flags=re.IGNORECASE)


def get_canonical_palette_html() -> str:
    """Generate a grid of the canonical brand palette for documentation."""
    palette = [
        # Brand & Semantic
        {"name": "Primary Navy", "hex": "#174092", "desc": "Brand primary color, used for ATLAS markers and UI accents.", "token": "--color-primary"},
        {"name": "OSM Matched Green", "hex": "#4CAF50", "desc": "Success color, used for matched OSM markers.", "token": "--color-success"},
        {"name": "ATLAS Unmatched Red", "hex": "#DC3545", "desc": "Danger color, used for unmatched ATLAS markers.", "token": "--color-danger"},
        {"name": "Priority P2 Orange", "hex": "#F0AD4E", "desc": "Warning color, used for significant problems.", "token": "--color-warning"},
        {"name": "OSM Unmatched Gray", "hex": "#6C757D", "desc": "Muted color, used for unmatched OSM markers.", "token": "--color-secondary"},
        
        # Neutral Scale
        {"name": "Neutral Dark", "hex": "#343a40", "desc": "Heading and primary text accent.", "token": "--color-dark"},
        {"name": "Neutral Muted", "hex": "#6C757D", "desc": "Secondary text and low-priority elements.", "token": "--color-fg-muted"},
        {"name": "System Border", "hex": "#E5E7EB", "desc": "Standard card and container borders.", "token": "--color-border"},
        {"name": "Subtle Surface", "hex": "#F8F9FA", "desc": "Subtle background for list headers and sections.", "token": "--color-bg-subtle"},
        {"name": "Primary Subtle", "hex": "#eef3fb", "desc": "Subtle background for info banners.", "token": "--color-primary-subtle"},
    ]
    
    html_parts = ['<div class="palette-grid mt-4 mb-5">']
    for color in palette:
        html_parts.append(f'''
        <div class="palette-card">
            <div class="palette-swatch" style="background-color: {color['hex']}"></div>
            <div class="palette-details">
                <div class="palette-name">{color['name']}</div>
                <div class="palette-meta">
                    <code class="palette-hex">{color['hex']}</code>
                    <code class="palette-token">{color['token']}</code>
                </div>
                <div class="palette-desc">{color['desc']}</div>
            </div>
        </div>''')
    html_parts.append('</div>')
    return ''.join(html_parts)
