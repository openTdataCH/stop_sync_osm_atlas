import os
from typing import List, Tuple

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
    if '](documentation/' in markdown_text:
        prefix = url_for("docs.docs_asset", filename="")  # ends with '/docs/assets/'
        markdown_text = markdown_text.replace('](documentation/', f']({prefix}')

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

    sidebar_items: List[Tuple[str, str]] = [(f, _derive_title(f)) for f in files]
    return render_template(
        'pages/docs.html',
        sidebar_items=sidebar_items,
        active_file=active_file,
        content_html=html_content,
    )


@docs_bp.route('/docs/assets/<path:filename>')
def docs_asset(filename: str):
    docs_dir = _get_docs_dir()
    return send_from_directory(docs_dir, filename)


