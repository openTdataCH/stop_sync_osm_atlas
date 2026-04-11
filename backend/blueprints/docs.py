import os
import time
import re
import json
import csv
import sys
import importlib
import subprocess
import logging
from typing import List, Tuple, Dict, Optional
from urllib.parse import unquote

from flask import Blueprint, render_template, abort, send_from_directory, request, url_for, jsonify, send_file, redirect
from werkzeug.utils import safe_join
from backend.services.docs_stats import replace_stats_placeholders

try:
    import mistune  # type: ignore
except Exception:  # pragma: no cover - optional at import time, ensured via requirements
    mistune = None

try:
    import bleach  # type: ignore
    try:
        CSSSanitizer = getattr(importlib.import_module('bleach.css_sanitizer'), 'CSSSanitizer', None)
    except ImportError:
        CSSSanitizer = None
except Exception:  # pragma: no cover
    bleach = None
    CSSSanitizer = None


docs_bp = Blueprint('docs', __name__)
logger = logging.getLogger(__name__)


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _docs_pdf_path() -> str:
    return os.path.join(_repo_root(), 'documentation', 'generated', 'stop_sync_osm_atlas_documentation_bw.pdf')


def ensure_docs_pdf_generated() -> bool:
    """Ensure the docs PDF exists and is fresh relative to its sources."""
    pdf_path = _docs_pdf_path()
    docs_dir = _get_docs_dir()
    stats_path = os.path.normpath(os.path.join(_repo_root(), 'data', 'stats.json'))
    
    is_fresh = os.path.exists(pdf_path)
    if is_fresh:
        pdf_mtime = os.path.getmtime(pdf_path)
        
        # 1. Check if stats.json is newer (stats injected in placeholders)
        if os.path.exists(stats_path) and os.path.getmtime(stats_path) > pdf_mtime:
            is_fresh = False
            
        # 2. Check if any markdown source file is newer
        if is_fresh:
            for f in os.listdir(docs_dir):
                if f.lower().endswith('.md'):
                    src_path = os.path.join(docs_dir, f)
                    if os.path.getmtime(src_path) > pdf_mtime:
                        is_fresh = False
                        break
        
        # 3. Check if the print CSS template is newer
        if is_fresh:
            css_path = os.path.normpath(os.path.join(docs_dir, 'pdf_generator', 'docs_print.css'))
            if os.path.exists(css_path) and os.path.getmtime(css_path) > pdf_mtime:
                is_fresh = False

    if is_fresh:
        return True

    generator_script = os.path.join(_repo_root(), 'documentation', 'pdf_generator', 'build_docs_pdf.py')
    if not os.path.exists(generator_script):
        logger.error("Docs PDF generator script not found at %s", generator_script)
        return False

    try:
        result = subprocess.run(
            [sys.executable, generator_script],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        logger.exception("Failed to execute docs PDF generator: %s", exc)
        return False

    if result.returncode != 0:
        logger.error(
            "Docs PDF generation failed (exit %s). stderr: %s",
            result.returncode,
            (result.stderr or '').strip()[-1000:],
        )
        return False

    return os.path.exists(pdf_path)


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


def _rewrite_internal_doc_links_to_routes(markdown_text: str, file_to_slug: Dict[str, str]) -> str:
    """Rewrite relative .md links to internal /docs/ Flask routes.

    Transforms links like [Text](1.%20Download%20and%20process%20data.md)
    into [Text](/docs/download_and_process_data) for canonical routing.
    """
    # Match [text](file.md) or [text](file.md#anchor)
    # Negative lookbehind avoids matching images: ![alt](...)
    pattern = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)]+\.md(?:#[^)]*)?)\)')

    def repl(match: re.Match) -> str:
        link_text = match.group(1)
        href = match.group(2)

        # Skip external links and absolute paths
        if href.startswith(('http://', 'https://', '/')):
            return match.group(0)

        # Split anchor if present
        if '#' in href:
            path_part, anchor = href.split('#', 1)
            anchor = '#' + anchor
        else:
            path_part = href
            anchor = ''

        clean_path = unquote(path_part).strip()
        clean_path = clean_path.lstrip('./')
        candidate_file = os.path.basename(clean_path)
        if not candidate_file.lower().endswith('.md'):
            candidate_file = f"{candidate_file}.md"

        slug = file_to_slug.get(candidate_file)
        if slug is None:
            # Keep unresolved links unchanged to avoid generating broken routes.
            return match.group(0)

        # Build Flask route URL
        new_href = url_for('docs.docs_page', page=slug) + anchor
        return f'[{link_text}]({new_href})'

    return pattern.sub(repl, markdown_text)


def _get_docs_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'documentation'))


def _list_markdown_files() -> List[str]:
    docs_dir = _get_docs_dir()
    files = [f for f in os.listdir(docs_dir) if f.lower().endswith('.md')]
    files.sort(key=lambda x: x.lower())
    return files


def _remove_numeric_prefix(stem: str) -> str:
    """Remove a leading numeric docs prefix like '2.1 ' or '5.3.2 '."""
    return re.sub(r'^\d+(?:\.\d+)*\.?\s*', '', stem).strip()


def _slugify_doc_stem(stem: str) -> str:
    """Create a URL-safe docs slug from a filename stem."""
    base = _remove_numeric_prefix(stem).lower()
    slug = re.sub(r'[^a-z0-9]+', '_', base).strip('_')
    return slug or 'doc'


def _build_doc_slug_maps(files: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Build deterministic filename<->slug maps for all docs files."""
    file_to_slug: Dict[str, str] = {}
    slug_to_file: Dict[str, str] = {}

    for filename in files:
        stem = os.path.splitext(filename)[0]
        base_slug = _slugify_doc_stem(stem)
        slug = base_slug
        counter = 2
        while slug in slug_to_file and slug_to_file[slug] != filename:
            slug = f"{base_slug}_{counter}"
            counter += 1

        file_to_slug[filename] = slug
        slug_to_file[slug] = filename

    return file_to_slug, slug_to_file


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


def _group_files_by_section(files: List[str], file_to_slug: Dict[str, str]) -> List[Dict]:
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
                'root_slug': None,
                'root_title': None,
                'items': []
            }
        if level <= 1:
            sections_map[key]['root_file'] = f
            sections_map[key]['root_title'] = title
            sections_map[key]['root_slug'] = file_to_slug.get(f, '')
        else:
            sections_map[key]['items'].append({
                'file': f,
                'slug': file_to_slug.get(f, ''),
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


def _convert_github_alerts_to_html(markdown_text: str) -> str:
    """
    Convert GitHub-style alerts/admonitions to styled HTML.
    
    Handles patterns like:
    > [!NOTE]
    > Content here
    
    Converts to styled divs with appropriate icons.
    """
    alert_types = {
        'NOTE': ('info-circle', 'alert-note'),
        'TIP': ('lightbulb', 'alert-tip'),
        'IMPORTANT': ('exclamation-circle', 'alert-important'),
        'WARNING': ('exclamation-triangle', 'alert-warning'),
        'CAUTION': ('radiation', 'alert-caution'),
    }
    
    # Pattern matches > [!TYPE] followed by > lines until end of block
    # This handles multi-line alerts
    def replace_alert(match):
        alert_type = match.group(1).upper()
        content = match.group(2)
        
        if alert_type not in alert_types:
            return match.group(0)
        
        icon, css_class = alert_types[alert_type]
        
        # Clean up the content - remove leading > from each line
        lines = content.strip().split('\n')
        cleaned_lines = []
        for line in lines:
            # Remove leading > and optional space
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
    
    # Match > [!TYPE]\n> content pattern (multi-line)
    # This regex captures the alert type and all subsequent > lines
    pattern = r'>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\n((?:>.*(?:\n|$))+)'
    
    return re.sub(pattern, replace_alert, markdown_text, flags=re.IGNORECASE)


def _get_canonical_palette_html() -> str:
    """Generate a beautiful grid of the canonical brand palette."""
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
    
    html = '<div class="palette-grid mt-4 mb-5">'
    for color in palette:
        html += f'''
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
        </div>'''
    html += '</div>'
    return html


def _convert_markdown_to_html(markdown_text: str, file_to_slug: Dict[str, str]) -> str:
    markdown_text = _rewrite_repo_links_to_github(markdown_text)
    
    # Rewrite internal .md links to Flask /docs/ routes
    markdown_text = _rewrite_internal_doc_links_to_routes(markdown_text, file_to_slug)
    
    # Convert GitHub-style alerts to HTML before markdown processing
    markdown_text = _convert_github_alerts_to_html(markdown_text)
    
    # Replace stats placeholders with actual values from stats.json
    markdown_text = replace_stats_placeholders(markdown_text)

    # Inject canonical palette grid if placeholder is present
    if '[[canonical_palette]]' in markdown_text:
        palette_html = _get_canonical_palette_html()
        markdown_text = markdown_text.replace('[[canonical_palette]]', palette_html)

    # Inject operator normalizations table if placeholder is present
    if '[[operator_normalizations_table]]' in markdown_text:
        table_html = _get_operator_normalizations_table_html()
        markdown_text = markdown_text.replace('[[operator_normalizations_table]]', table_html)

    # Rewrite repo-relative image/asset paths to the docs assets route
    # Example: ![...](images/foo.png) -> ![...](/docs/assets/images/foo.png)
    if (
        '](documentation/' in markdown_text
        or '](images/' in markdown_text
        or 'src="documentation/' in markdown_text
        or 'src="images/' in markdown_text
    ):
        prefix = url_for("docs.docs_asset", filename="")  # ends with '/docs/assets/'
        
        # Markdown image/link paths
        markdown_text = markdown_text.replace('](documentation/', f']({prefix}')
        markdown_text = markdown_text.replace('](images/', f']({prefix}images/')
        
        # Raw HTML img tags inside markdown
        markdown_text = markdown_text.replace('src="documentation/', f'src="{prefix}')
        markdown_text = markdown_text.replace('src="images/', f'src="{prefix}images/')

    if mistune is None:
        return '<p>Markdown renderer not available. Please install dependencies.</p>'

    # Protect LaTeX backslashes from mistune's escape processing
    # inside $$ ... $$ and $ ... $ blocks.
    def _protect_math(match):
        return match.group(0).replace('\\', '\\\\')
    
    markdown_text = re.sub(r'\$\$.*?\$\$', _protect_math, markdown_text, flags=re.DOTALL)
    # Inline math protection: $ followed by non-space, ending with non-space before $, 
    # and not preceded or followed by other dollars. Supports single char like $B$.
    markdown_text = re.sub(r'(?<!\$)\$[^\s$](?:.*?[^\s$])?\$(?!\$)', _protect_math, markdown_text)

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
        'p', 'pre', 'code', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'span', 'div', 'i',
        'details', 'summary'
    ]
    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'img': ['src', 'alt', 'title'],
        'a': ['href', 'title', 'name', 'target', 'rel'],
        'span': ['class', 'data-stat-key', 'title', 'style'],
        'div': ['class', 'style'],
        'i': ['class'],
        'details': ['class', 'open'],
        'summary': ['class']
    }
    css_sanitizer = None
    if CSSSanitizer:
        css_sanitizer = CSSSanitizer(allowed_css_properties=['background-color'])

    clean_kwargs = {
        'tags': allowed_tags,
        'attributes': allowed_attrs,
    }
    if css_sanitizer is not None:
        clean_kwargs['css_sanitizer'] = css_sanitizer

    try:
        sanitized = bleach.clean(html, **clean_kwargs)
    except TypeError:
        # Older Bleach versions don't support css_sanitizer.
        clean_kwargs.pop('css_sanitizer', None)
        sanitized = bleach.clean(html, **clean_kwargs)
    sanitized = bleach.linkify(sanitized)
    return sanitized


@docs_bp.route('/docs')
@docs_bp.route('/docs/<path:page>')
def docs_page(page: str = ''):
    files = _list_markdown_files()
    if not files:
        abort(404)

    file_to_slug, slug_to_file = _build_doc_slug_maps(files)

    def resolve_active_file(requested_page: str) -> Optional[str]:
        if not requested_page:
            return None

        decoded_page = unquote(requested_page).strip('/')
        if not decoded_page:
            return None

        # Canonical slug lookup.
        by_slug = slug_to_file.get(decoded_page)
        if by_slug:
            return by_slug

        # Legacy filename lookup (with or without .md extension).
        candidate = decoded_page if decoded_page.lower().endswith('.md') else f"{decoded_page}.md"
        if candidate in file_to_slug:
            return candidate

        # Fallback for loosely formatted legacy links.
        fallback_slug = _slugify_doc_stem(os.path.splitext(decoded_page)[0])
        return slug_to_file.get(fallback_slug)

    is_partial = request.headers.get('X-Docs-Partial') == '1' or request.args.get('partial') == '1'

    # If no page specified, default to the first doc
    active_file = resolve_active_file(page)
    if not page:
        active_file = files[0]
    elif active_file is None:
        abort(404)

    active_slug = file_to_slug.get(active_file, '')

    # Redirect legacy/non-canonical URLs to canonical slugs for clean URLs.
    if page and unquote(page).strip('/') != active_slug and not is_partial:
        return redirect(url_for('docs.docs_page', page=active_slug), code=301)

    if active_file is None:
        active_file = files[0]

    raw_markdown = _read_markdown(active_file)
    html_content = _convert_markdown_to_html(raw_markdown, file_to_slug)

    sections = _group_files_by_section(files, file_to_slug)
    # Build an ordered flat list for prev/next navigation
    ordered_pages: List[Dict[str, str]] = []
    for sec in sections:
        if sec.get('root_file'):
            ordered_pages.append({
                'file': sec['root_file'],
                'slug': file_to_slug.get(sec['root_file'], ''),
                'title': sec.get('root_title') or _derive_title(sec['root_file']),
            })
        for item in sec['items']:
            ordered_pages.append({
                'file': item['file'],
                'slug': item.get('slug', ''),
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

    if prev_page:
        prev_page = {
            'file': prev_page['file'],
            'slug': prev_page.get('slug', file_to_slug.get(prev_page['file'], '')),
            'title': prev_page['title'],
        }
    if next_page:
        next_page = {
            'file': next_page['file'],
            'slug': next_page.get('slug', file_to_slug.get(next_page['file'], '')),
            'title': next_page['title'],
        }

    active_section = _top_level_section_key(active_file)

    if is_partial:
        return jsonify({
            'content_html': html_content,
            'active_file': active_file,
            'active_slug': active_slug,
            'active_section': active_section,
            'prev_page': prev_page,
            'next_page': next_page,
            'canonical_url': url_for('docs.docs_page', page=active_slug),
        })

    return render_template(
        'pages/docs.html',
        sections=sections,
        active_file=active_file,
        active_slug=active_slug,
        active_section=active_section,
        content_html=html_content,
        prev_page=prev_page,
        next_page=next_page,
    )


@docs_bp.route('/docs/assets/<path:filename>')
def docs_asset(filename: str):
    docs_dir = _get_docs_dir()
    return send_from_directory(docs_dir, filename)


@docs_bp.route('/api/docs/download_pdf', methods=['GET'])
def download_docs_pdf():
    """Download the generated documentation PDF (generate it if missing)."""
    if not ensure_docs_pdf_generated():
        return jsonify({
            "error": "Could not generate documentation PDF. Run the 'Docs: Build PDF' task and check logs.",
        }), 500

    return send_file(
        _docs_pdf_path(),
        mimetype='application/pdf',
        as_attachment=True,
        download_name='stop_sync_osm_atlas_documentation.pdf',
    )


def _get_operator_normalizations_table_html() -> str:
    """Read the CSV and return a styled HTML table for embedding."""
    csv_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', '..', 'matching_and_import_db', 'utils', 'operator_normalizations.csv'
    ))
    
    if not os.path.isfile(csv_path):
        return '<p class="text-muted"><em>Mappings file not found.</em></p>'
    
    try:
        rows = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        if not rows:
            return '<p class="text-muted"><em>No active mappings found.</em></p>'

        html = '<details class="doc-expandable-section mb-4">'
        html += '<summary class="doc-expandable-summary">View current normalization mappings (' + str(len(rows)) + ')</summary>'
        html += '<div class="doc-expandable-content">'
        html += '<table class="table table-sm table-hover">'
        html += '<thead><tr><th>Alias</th><th>Normalized Name</th></tr></thead>'
        html += '<tbody>'
        for row in rows:
            html += f'<tr><td><code>{row.get("alias", "")}</code></td><td><strong>{row.get("standard_name", "")}</strong></td></tr>'
        html += '</tbody></table>'
        html += '<div class="small text-muted mt-2"><i class="fas fa-file-csv"></i> Source: <code>matching_and_import_db/utils/operator_normalizations.csv</code></div>'
        html += '</div></details>'
        return html
    except Exception as e:
        logger.error("Error generating operator normalizations table: %s", e)
        return f'<p class="text-danger"><small>Error loading mappings: {str(e)}</small></p>'


@docs_bp.route('/api/docs/stats')
def get_documentation_stats():
    """
    Get statistics for documentation rendering.
    
    Returns a combination of:
    1. Pipeline stats from data/stats.json (generated during import)
    2. Real-time stats from database (problem counts and stop health)
    
    This endpoint is used to dynamically populate statistics in documentation pages.
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

    These stats reflect current DB state and should not be cached
    in the static stats.json file.
    """
    try:
        from backend.extensions import db
        from backend.models import StopsMatched, Problem
        from sqlalchemy import func
        
        # Total stops in database
        total_stops = db.session.query(func.count(StopsMatched.id)).scalar() or 0
        
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
        
        # Problem resolution state is not persisted in the current schema.
        solved_problems = 0
        unsolved_problems = total_problems
        
        # Stops with problems vs clean stops
        stops_with_problems = db.session.query(
            func.count(func.distinct(Problem.stop_id))
        ).scalar() or 0
        clean_stops = total_stops - stops_with_problems
        
        resolution_rate = 0.0
        
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


