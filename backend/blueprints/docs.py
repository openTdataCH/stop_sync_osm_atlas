import os
import re
import json
from typing import List, Tuple, Dict, Optional

from flask import Blueprint, render_template, abort, send_from_directory, request, url_for, jsonify
from werkzeug.utils import safe_join

try:
    import mistune  # type: ignore
except Exception:  # pragma: no cover - optional at import time, ensured via requirements
    mistune = None

try:
    import bleach  # type: ignore
except Exception:  # pragma: no cover
    bleach = None


docs_bp = Blueprint('docs', __name__)


def _github_blob_base() -> str:
    """Base URL for linking to repository files on GitHub.

    Can be overridden with DOCS_GITHUB_BLOB_BASE (must end with '/').
    """
    base = os.environ.get(
        'DOCS_GITHUB_BLOB_BASE',
        'https://github.com/openTdataCH/stop_sync_osm_atlas/blob/main/',
    )
    if not base.endswith('/'):
        base += '/'
    return base


_CODE_FILE_EXTENSIONS = {
    '.py', '.sql', '.sh', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg',
    '.js', '.ts', '.tsx', '.jsx', '.css', '.html',
}


def _looks_like_repo_file_link(href: str) -> bool:
    if not href:
        return False
    lower = href.lower()
    if lower.startswith(('http://', 'https://', 'mailto:', '#')):
        return False
    # Docs assets are served locally (images/diagrams/documentation/*) and are
    # handled separately.
    if lower.startswith(('documentation/', 'images/', 'diagrams/')):
        return False

    path = href.split('#', 1)[0].split('?', 1)[0]
    # Common repo root files without extensions.
    if os.path.basename(path).lower() in {'dockerfile'}:
        return True
    _, ext = os.path.splitext(path)
    if not ext:
        return False
    if ext.lower() in _CODE_FILE_EXTENSIONS:
        return True
    return False


def _normalize_repo_relative_path(href: str) -> str:
    # Drop query/fragment for blob path; keep them to re-append later.
    base_part, frag = (href.split('#', 1) + [''])[:2]
    base_part, query = (base_part.split('?', 1) + [''])[:2]

    path = base_part.strip()
    path = path.lstrip('/')
    while path.startswith('../'):
        path = path[3:]
    if path.startswith('./'):
        path = path[2:]

    rebuilt = path
    if query:
        rebuilt += f"?{query}"
    if frag:
        rebuilt += f"#{frag}"
    return rebuilt


def _rewrite_repo_links_to_github(markdown_text: str) -> str:
    """Rewrite markdown links that point to repo files into GitHub blob links."""

    # Match standard markdown links: [text](href "optional title")
    # Negative lookbehind avoids matching images: ![alt](...)
    pattern = re.compile(r'(?<!\!)\]\(([^\s)]+)(\s+"[^"]*")?\)')

    def repl(match: re.Match) -> str:
        href = match.group(1)
        title = match.group(2) or ''
        if not _looks_like_repo_file_link(href):
            return match.group(0)
        normalized = _normalize_repo_relative_path(href)
        new_href = f"{_github_blob_base()}{normalized}".replace(' ', '%20')
        return f"]({new_href}{title})"

    return pattern.sub(repl, markdown_text)


def _get_docs_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'documentation'))


def _list_markdown_files() -> List[str]:
    docs_dir = _get_docs_dir()
    files = [f for f in os.listdir(docs_dir) if f.lower().endswith('.md')]
    files.sort(key=lambda x: x.lower())
    return files


def _derive_title(filename: str) -> str:
    return os.path.splitext(filename)[0].replace('_', ' ').title()


def _derive_level(filename: str) -> int:
    """Return hierarchical level inferred from numeric prefix.

    Examples:
    - "1. Foo.md" -> 1
    - "1.1 Bar.md" -> 2
    - "1.2.3 Baz.md" -> 3
    Non-numbered files -> 0
    """
    name = os.path.splitext(filename)[0]
    first_token = name.split(' ')[0] if ' ' in name else name
    trimmed = first_token.rstrip('.')
    if not trimmed or not trimmed[0].isdigit():
        return 0
    # Ensure the token is composed of digits and dots
    if not all(ch.isdigit() or ch == '.' for ch in trimmed):
        return 0
    segments = [seg for seg in trimmed.split('.') if seg]
    if not segments or not all(seg.isdigit() for seg in segments):
        return 0
    return len(segments)


def _top_level_section_key(filename: str) -> Optional[str]:
    """Return the top-level numeric section as a string (e.g. '0', '1'), or None."""
    name = os.path.splitext(filename)[0]
    first_token = name.split(' ')[0] if ' ' in name else name
    trimmed = first_token.rstrip('.')
    if not trimmed or not trimmed[0].isdigit():
        return None
    if not all(ch.isdigit() or ch == '.' for ch in trimmed):
        return None
    top = trimmed.split('.')[0]
    if not top.isdigit():
        return None
    return top


def _group_files_by_section(files: List[str]) -> List[Dict]:
    """Group markdown files by their top-level numeric section.

    Returns a list of sections sorted by numeric key. Each section is a dict:
    { 'key': '1', 'number': 1, 'root_file': '1. Title.md', 'root_title': '1. Title',
      'items': [ { 'file': '1.1 Foo.md', 'title': '1.1 Foo', 'level': 2 }, ... ] }
    Root file is the level-1 file for that section if present; items include only
    files with level > 1 belonging to the section.
    """
    sections_map: Dict[str, Dict] = {}
    for f in files:
        key = _top_level_section_key(f)
        if key is None:
            continue
        level = _derive_level(f)
        title = _derive_title(f)
        if key not in sections_map:
            sections_map[key] = {
                'key': key,
                'number': int(key),
                'root_file': None,
                'root_title': None,
                'items': []
            }
        if level <= 1:
            sections_map[key]['root_file'] = f
            sections_map[key]['root_title'] = title
        else:
            sections_map[key]['items'].append({
                'file': f,
                'title': title,
                'level': level,
            })

    for sec in sections_map.values():
        sec['items'].sort(key=lambda it: it['file'].lower())

    sections = sorted(sections_map.values(), key=lambda s: s['number'])
    return sections


def _read_markdown(filename: str) -> str:
    docs_dir = _get_docs_dir()
    safe_path = safe_join(docs_dir, filename)
    if not safe_path or not os.path.isfile(safe_path):
        abort(404)
    with open(safe_path, 'r', encoding='utf-8') as f:
        return f.read()


def _convert_markdown_to_html(markdown_text: str) -> str:
    markdown_text = _rewrite_repo_links_to_github(markdown_text)
    
    # Replace stats placeholders with actual values from stats.json
    markdown_text = _replace_stats_placeholders(markdown_text)

    # Rewrite repo-relative image/asset paths to the docs assets route
    # Example: !(...](documentation/images/foo.png) -> !(...](/docs/assets/images/foo.png)
    # For SVG diagrams, use the dynamic stats endpoint to inject live values
    if (
        '](documentation/' in markdown_text
        or '](images/' in markdown_text
        or '](diagrams/' in markdown_text
        or 'src="documentation/' in markdown_text
        or 'src="images/' in markdown_text
        or 'src="diagrams/' in markdown_text
    ):
        prefix = url_for("docs.docs_asset", filename="")  # ends with '/docs/assets/'
        svg_prefix = url_for("docs.get_svg_with_stats", svg_name="")  # for SVG diagrams with stats
        
        # For SVG files in diagrams/, use the dynamic endpoint
        # Match patterns like ](diagrams/overview.svg) and replace with dynamic endpoint
        markdown_text = re.sub(
            r'\]\(diagrams/([^)]+\.svg)\)',
            lambda m: f']({svg_prefix}{m.group(1)})',
            markdown_text
        )
        
        # Markdown image/link paths (non-SVG diagrams and other assets)
        markdown_text = markdown_text.replace('](documentation/', f']({prefix}')
        markdown_text = markdown_text.replace('](images/', f']({prefix}images/')
        # Only replace non-SVG diagram references (SVGs already handled above)
        markdown_text = re.sub(
            r'\]\(diagrams/([^)]+(?<!\.svg))\)',
            lambda m: f']({prefix}diagrams/{m.group(1)})',
            markdown_text
        )
        
        # Raw HTML img tags inside markdown
        markdown_text = markdown_text.replace('src="documentation/', f'src="{prefix}')
        markdown_text = markdown_text.replace('src="images/', f'src="{prefix}images/')
        # For SVG src attributes, use dynamic endpoint
        markdown_text = re.sub(
            r'src="diagrams/([^"]+\.svg)"',
            lambda m: f'src="{svg_prefix}{m.group(1)}"',
            markdown_text
        )
        markdown_text = re.sub(
            r'src="diagrams/([^"]+(?<!\.svg))"',
            lambda m: f'src="{prefix}diagrams/{m.group(1)}"',
            markdown_text
        )

    if mistune is None:
        return '<p>Markdown renderer not available. Please install dependencies.</p>'

    md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'table', 'url'])
    html = md(markdown_text)
    
    # Convert mermaid code blocks to mermaid divs for client-side rendering
    # Pattern matches: <pre><code class="language-mermaid">...</code></pre>
    html = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<div class="mermaid">{m.group(1)}</div>',
        html,
        flags=re.DOTALL
    )

    if bleach is None:
        return html

    allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
        'p', 'pre', 'code', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'span', 'div'
    ]
    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'img': ['src', 'alt', 'title'],
        'a': ['href', 'title', 'name', 'target', 'rel'],
        'span': ['class', 'data-stat-key', 'title'],
        'div': ['class']
    }
    sanitized = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)
    sanitized = bleach.linkify(sanitized)
    return sanitized


def _load_stats_for_docs() -> Optional[Dict]:
    """Load stats from data/stats.json for documentation rendering."""
    try:
        stats_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'stats.json'
        )
        if os.path.exists(stats_file_path):
            with open(stats_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _get_nested_stat_value(stats: Dict, key_path: str):
    """Get a nested value from stats dictionary using dot notation."""
    if not stats:
        return None
    keys = key_path.split('.')
    value = stats
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def _format_stat_value(value) -> str:
    """Format a stat value for display."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        # Format percentages nicely
        if value < 1 and value > 0:
            return f"{value:.1%}"
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _replace_stats_placeholders(markdown_text: str) -> str:
    """
    Replace {{stat:key.path}} placeholders in markdown with actual stat values.
    
    Supports:
    - {{stat:summary.matched_pairs}} -> formatted value
    - {{stat:summary.match_rate_percent}}% -> formatted value with %
    
    Values are wrapped in <span> tags with data attributes for potential
    client-side updates and styling.
    """
    stats = _load_stats_for_docs()
    
    # Pattern matches {{stat:key.path}} including optional formatting
    pattern = r'\{\{stat:([a-zA-Z0-9_.]+)\}\}'
    
    def replace_match(match):
        key_path = match.group(1)
        value = _get_nested_stat_value(stats, key_path)
        formatted = _format_stat_value(value)
        
        # Wrap in span for styling and potential JS updates
        css_class = "dynamic-stat"
        if value is None:
            css_class += " stat-unavailable"
        
        return f'<span class="{css_class}" data-stat-key="{key_path}" title="Auto-updated from pipeline stats">{formatted}</span>'
    
    return re.sub(pattern, replace_match, markdown_text)


@docs_bp.route('/docs')
@docs_bp.route('/docs/<path:page>')
def docs_page(page: str = ''):
    files = _list_markdown_files()
    if not files:
        abort(404)

    # If no page specified, default to the first doc
    active_file = None
    if page:
        # Accept either with or without .md
        candidate = page if page.lower().endswith('.md') else f"{page}.md"
        if candidate in files:
            active_file = candidate
    if active_file is None:
        active_file = files[0]

    raw_markdown = _read_markdown(active_file)
    html_content = _convert_markdown_to_html(raw_markdown)

    sections = _group_files_by_section(files)
    # Build an ordered flat list for prev/next navigation
    ordered_pages: List[Dict[str, str]] = []
    for sec in sections:
        if sec.get('root_file'):
            ordered_pages.append({
                'file': sec['root_file'],
                'title': sec.get('root_title') or _derive_title(sec['root_file']),
            })
        for item in sec['items']:
            ordered_pages.append({
                'file': item['file'],
                'title': item['title'],
            })

    prev_page: Optional[Dict[str, str]] = None
    next_page: Optional[Dict[str, str]] = None
    try:
        idx = next(i for i, p in enumerate(ordered_pages) if p['file'] == active_file)
        if idx > 0:
            prev_page = ordered_pages[idx - 1]
        if idx < len(ordered_pages) - 1:
            next_page = ordered_pages[idx + 1]
    except StopIteration:
        prev_page = None
        next_page = None
    active_section = _top_level_section_key(active_file)
    return render_template(
        'pages/docs.html',
        sections=sections,
        active_file=active_file,
        active_section=active_section,
        content_html=html_content,
        prev_page=prev_page,
        next_page=next_page,
    )


@docs_bp.route('/docs/assets/<path:filename>')
def docs_asset(filename: str):
    docs_dir = _get_docs_dir()
    return send_from_directory(docs_dir, filename)


@docs_bp.route('/api/docs/stats')
def get_documentation_stats():
    """
    Get statistics for documentation rendering.
    
    Returns a combination of:
    1. Pipeline stats from data/stats.json (generated during import)
    2. Real-time stats from database (problem resolutions, user activity)
    
    This endpoint is used to dynamically populate statistics in documentation
    pages and can also update SVG diagrams with current values.
    """
    try:
        # Load pipeline stats from file
        stats_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'stats.json'
        )
        
        pipeline_stats = None
        if os.path.exists(stats_file_path):
            with open(stats_file_path, 'r', encoding='utf-8') as f:
                pipeline_stats = json.load(f)
        
        # Get real-time stats from database
        realtime_stats = _get_realtime_db_stats()
        
        response = {
            "pipeline": pipeline_stats,
            "realtime": realtime_stats,
            "available": pipeline_stats is not None,
        }
        
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e), "available": False}), 500


def _get_realtime_db_stats() -> Dict:
    """
    Get real-time statistics from the database.
    
    These stats reflect current state including user problem resolutions,
    and should not be cached in the static stats.json file.
    """
    try:
        from backend.extensions import db
        from backend.models import Stop, Problem, PersistentData
        from sqlalchemy import func
        
        # Total stops in database
        total_stops = db.session.query(func.count(Stop.id)).scalar() or 0
        
        # Problem statistics
        total_problems = db.session.query(func.count(Problem.id)).scalar() or 0
        
        # Problems by type
        problems_by_type = dict(
            db.session.query(Problem.problem_type, func.count(Problem.id))
            .group_by(Problem.problem_type)
            .all()
        )
        
        # Problems by priority
        problems_by_priority = dict(
            db.session.query(Problem.priority, func.count(Problem.id))
            .group_by(Problem.priority)
            .all()
        )
        
        # Solved vs unsolved problems
        solved_problems = db.session.query(func.count(Problem.id)).filter(
            Problem.solution.isnot(None),
            Problem.solution != ''
        ).scalar() or 0
        unsolved_problems = total_problems - solved_problems
        
        # Persistent solutions count
        persistent_solutions = db.session.query(func.count(PersistentData.id)).scalar() or 0
        
        # Manual matches count
        manual_matches = db.session.query(func.count(PersistentData.id)).filter(
            PersistentData.problem_type == 'unmatched',
            PersistentData.solution == 'manual'
        ).scalar() or 0
        
        # Stops with problems vs clean stops
        stops_with_problems = db.session.query(
            func.count(func.distinct(Problem.stop_id))
        ).scalar() or 0
        clean_stops = total_stops - stops_with_problems
        
        # Calculate resolution rate
        resolution_rate = (solved_problems / total_problems * 100) if total_problems > 0 else 0
        
        return {
            "total_stops": total_stops,
            "problems": {
                "total": total_problems,
                "solved": solved_problems,
                "unsolved": unsolved_problems,
                "resolution_rate_percent": round(resolution_rate, 1),
                "by_type": {
                    "distance": problems_by_type.get('distance', 0),
                    "unmatched": problems_by_type.get('unmatched', 0),
                    "attributes": problems_by_type.get('attributes', 0),
                    "duplicates": problems_by_type.get('duplicates', 0),
                },
                "by_priority": {
                    "p1_high": problems_by_priority.get(1, 0),
                    "p2_medium": problems_by_priority.get(2, 0),
                    "p3_low": problems_by_priority.get(3, 0),
                }
            },
            "persistent_data": {
                "total_solutions": persistent_solutions,
                "manual_matches": manual_matches,
            },
            "stops_health": {
                "with_problems": stops_with_problems,
                "clean": clean_stops,
            }
        }
    except Exception as e:
        # Return empty stats if database is not available
        return {
            "error": str(e),
            "total_stops": 0,
            "problems": {
                "total": 0,
                "solved": 0,
                "unsolved": 0,
                "resolution_rate_percent": 0,
                "by_type": {},
                "by_priority": {}
            }
        }


@docs_bp.route('/api/docs/stats/svg/<path:svg_name>')
def get_svg_with_stats(svg_name: str):
    """
    Serve an SVG diagram with dynamic statistics injected.
    
    This endpoint reads the SVG file, replaces placeholder values with
    current statistics, and returns the updated SVG.
    
    Placeholders in SVG files should use the format: {{stat_key}}
    Example: {{summary.matched_pairs}} or {{summary.match_rate_percent}}
    """
    try:
        docs_dir = _get_docs_dir()
        svg_path = safe_join(docs_dir, 'diagrams', svg_name)
        
        if not svg_path or not os.path.exists(svg_path):
            abort(404)
        
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # Load stats
        stats_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'stats.json'
        )
        
        if os.path.exists(stats_file_path):
            with open(stats_file_path, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            
            # Replace placeholders with actual values
            svg_content = _replace_svg_placeholders(svg_content, stats)
        
        from flask import Response
        return Response(svg_content, mimetype='image/svg+xml')
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _replace_svg_placeholders(svg_content: str, stats: Dict) -> str:
    """
    Replace {{placeholder}} patterns in SVG with actual stat values.
    
    Supports nested keys like {{summary.matched_pairs}}.
    """
    def get_nested_value(data: Dict, key_path: str):
        """Get a nested value from a dictionary using dot notation."""
        keys = key_path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value
    
    # Find all placeholders in the format {{key}} or {{key.subkey}}
    pattern = r'\{\{([a-zA-Z0-9_.]+)\}\}'
    
    def replace_match(match):
        key_path = match.group(1)
        value = get_nested_value(stats, key_path)
        if value is not None:
            # Format numbers with commas for readability
            if isinstance(value, (int, float)):
                if isinstance(value, float):
                    return f"{value:,.1f}"
                return f"{value:,}"
            return str(value)
        return match.group(0)  # Return original if not found
    
    return re.sub(pattern, replace_match, svg_content)


