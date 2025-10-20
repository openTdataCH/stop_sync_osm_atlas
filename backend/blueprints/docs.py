import os
from typing import List, Tuple, Dict, Optional

from flask import Blueprint, render_template, abort, send_from_directory, request, url_for
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
    # Rewrite repo-relative image/asset paths to the docs assets route
    # Example: !(...](documentation/images/foo.png) -> !(...](/docs/assets/images/foo.png)
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

    md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'table', 'url'])
    html = md(markdown_text)

    if bleach is None:
        return html

    allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
        'p', 'pre', 'code', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr'
    ]
    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'img': ['src', 'alt', 'title'],
        'a': ['href', 'title', 'name', 'target', 'rel']
    }
    sanitized = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)
    sanitized = bleach.linkify(sanitized)
    return sanitized


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


