"""The documentation portal at /docs and its PDF export.

The pages, their addresses and the sidebar come from
``backend/services/docs_sources.py``; ``backend/services/docs_render.py``
turns a page into safe HTML.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory, url_for
from markupsafe import Markup

from backend.services.async_export import start_task
from backend.services.docs_render import convert_markdown_to_html
from backend.services.docs_sources import (
    DOC_SOURCES, build_doc_collections, build_doc_slug_maps, display_title, docs_dirs, list_markdown_files,
    normalize_section_key, owner_prefix, read_markdown, reading_order, split_nav_number,
)
from backend.services.request_payload import read_request_payload
from backend.services.site_url import site_url
from backend.version import APP_ROOT

docs_bp = Blueprint('docs', __name__)
logger = logging.getLogger(__name__)


def _to_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    return default


def _payload_list(value) -> Optional[List[str]]:
    """Read a list from JSON, a JSON-encoded string or a comma-separated field."""
    if isinstance(value, str):
        stripped = value.strip()
        parsed = None
        if stripped.startswith('['):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                pass
        value = parsed if isinstance(parsed, list) else (stripped.split(',') if stripped else [])
    if not isinstance(value, list):
        return None
    return [str(item).strip() for item in value]


def _to_sections_list(value) -> Optional[List[str]]:
    sections = [key for key in map(normalize_section_key, _payload_list(value) or []) if key is not None]
    return sections or None


def _to_pages_list(value) -> Optional[List[str]]:
    """Page addresses (``reference_matching``) for a single-page export."""
    pages = [page for page in _payload_list(value) or [] if page]
    return pages or None


_DOCS_PDF = 'documentation/generated/stop_sync_osm_atlas_documentation.pdf'
_PDF_GENERATOR = 'documentation/pdf_generator/build_docs_pdf.py'
# What the whole-documentation PDF is made from, besides the pages and their images.
_PDF_INPUTS = (
    'data/stats.json',
    'quality/published/publication.json',
    'backend/services/docs_*.py',
    'backend/services/quality_report.py',
    'documentation/pdf_generator/*',
)
_PAGE_SUFFIXES = {'.md', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf'}


def _docs_pdf_path() -> Path:
    return APP_ROOT / _DOCS_PDF


def _newest_pdf_input() -> float:
    """When the newest page, image, statistic, quality artifact, print style or renderer changed."""
    paths = [path for pattern in _PDF_INPUTS for path in APP_ROOT.glob(pattern)]
    for directory in docs_dirs().values():
        for root, child_dirs, files in os.walk(directory):
            child_dirs[:] = [name for name in child_dirs if name != 'generated']
            paths += [Path(root, name) for name in files if os.path.splitext(name)[1].lower() in _PAGE_SUFFIXES]
    return max((path.stat().st_mtime for path in paths if path.is_file()), default=0.0)


def ensure_docs_pdf_generated() -> bool:
    """Rebuild the cached whole-documentation PDF when one of its inputs is newer.

    The build runs in its own process. When it fails, an older PDF is kept and served.
    """
    pdf_path = _docs_pdf_path()
    if pdf_path.exists() and pdf_path.stat().st_mtime >= _newest_pdf_input():
        return True
    result = subprocess.run(
        [sys.executable, str(APP_ROOT / _PDF_GENERATOR)],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.error(
            'Docs PDF generation failed (exit %s). stderr: %s',
            result.returncode,
            (result.stderr or '').strip()[-1000:],
        )
    return pdf_path.exists()


# Pages that describe another page of the site link to it from their header,
# next to the PDF export.
_PAGE_HEADER_LINKS = {
    'documentation/4.3 Code quality.md': (
        {'endpoint': 'quality.quality_dashboard', 'label': 'Open the dashboard', 'icon': 'fa-project-diagram'},
    ),
}

_PAGE_TITLE_PATTERN = re.compile(r'\s*<h1>(?P<title>.*?)</h1>\s*', re.DOTALL)


def _page_header(html: str, doc_id: str, collection: Optional[Dict], slug: str, section: Optional[str]) -> Tuple[Dict, str]:
    """Move the page's ``#`` heading from the article into the page header.

    The header shows the collection, in its owner's colour, and the page
    number above the title, then the page's links to other pages of the
    site (``_PAGE_HEADER_LINKS``). Its PDF link carries the page's address,
    section and label for the export dialog. Returns the header and the
    article without its heading.
    """
    number, title_html = None, None
    match = _PAGE_TITLE_PATTERN.match(html)
    if match:
        number, title_html = split_nav_number(match.group('title').strip(), owner_prefix(doc_id))
        html = html[match.end():]
    title_text = Markup(title_html).striptags() if title_html else display_title(doc_id)
    return {
        'collection': collection['label'] if collection else None,
        'owner': collection['owner'] if collection else None,
        'number': number,
        'title_html': title_html,
        'slug': slug,
        'section': section,
        'label': f'{number} {title_text}' if number else title_text,
        'links': _PAGE_HEADER_LINKS.get(doc_id, ()),
    }, html


@docs_bp.route('/docs')
@docs_bp.route('/docs/<path:page>')
def docs_page(page: str = ''):
    files = list_markdown_files()
    if not files:
        abort(404)

    file_to_slug, slug_to_file = build_doc_slug_maps(files)
    # A page opens only at its address; /docs opens the first page.
    active_file = slug_to_file.get(unquote(page).strip('/')) if page else files[0]
    if active_file is None:
        abort(404)
    active_slug = file_to_slug.get(active_file, '')

    try:
        raw_markdown = read_markdown(active_file)
    except FileNotFoundError:
        abort(404)
    html_content = convert_markdown_to_html(raw_markdown, file_to_slug, active_file)
    active_title = display_title(active_file)
    collections = build_doc_collections(files, file_to_slug)

    def page_link(doc_id: str) -> Dict[str, str]:
        return {'file': doc_id, 'slug': file_to_slug.get(doc_id, ''), 'title': display_title(doc_id)}

    # Previous and next follow the sidebar.
    order = reading_order(collections)
    index = next((i for i, (_, _, doc_id) in enumerate(order) if doc_id == active_file), None)
    active_collection = active_section = prev_page = next_page = None
    if index is not None:
        active_collection, section, _ = order[index]
        active_section = section['key']
        prev_page = page_link(order[index - 1][2]) if index > 0 else None
        next_page = page_link(order[index + 1][2]) if index + 1 < len(order) else None

    page_header, html_content = _page_header(
        html_content, active_file, active_collection, active_slug, active_section,
    )

    if request.headers.get('X-Docs-Partial') == '1' or request.args.get('partial') == '1':
        return jsonify({
            'content_html': html_content,
            'header_html': render_template('components/docs_page_header.html', page_header=page_header),
            'active_file': active_file,
            'active_slug': active_slug,
            'active_section': active_section,
            'title': active_title,
            'prev_page': prev_page,
            'next_page': next_page,
            'canonical_url': url_for('docs.docs_page', page=active_slug),
        })

    return render_template(
        'pages/docs.html',
        collections=collections,
        active_slug=active_slug,
        active_section=active_section,
        active_title=active_title,
        page_header=page_header,
        content_html=html_content,
        prev_page=prev_page,
        next_page=next_page,
        seo_canonical_url=site_url(
            url_for('docs.docs_page', page=active_slug),
        ),
    )


@docs_bp.route('/docs/assets/<path:filename>')
def docs_asset(filename: str):
    source_key, separator, relative_path = filename.partition('/')
    if not separator or source_key not in DOC_SOURCES:
        # Preserve old app-owned asset URLs during the transition.
        source_key = 'app'
        relative_path = filename
    return send_from_directory(docs_dirs()[source_key], relative_path)


@docs_bp.route('/api/docs/generate_pdf_async', methods=['POST'])
def generate_docs_pdf_async():
    """Start a PDF export; /api/exports/<task_id>/… reports its progress and serves the file."""
    data = read_request_payload(request, include_query_args=False)
    included_sections = _to_sections_list(data.get('included_sections'))  # None means all
    included_pages = _to_pages_list(data.get('included_pages'))
    include_cover = _to_bool(data.get('include_cover'), default=True)
    selected_only = _to_bool(data.get('selected_only'), default=False)

    page_files = None
    if included_pages:
        _, slug_to_file = build_doc_slug_maps(list_markdown_files())
        unknown = [page for page in included_pages if page not in slug_to_file]
        if unknown:
            return jsonify({"error": f"Unknown documentation page: {unknown[0]}"}), 400
        page_files = [slug_to_file[page] for page in included_pages]

    if selected_only and not included_sections and not page_files:
        return jsonify({"error": "No sections selected for partial documentation export."}), 400
    # A single page downloads under its own address.
    download_name = f'{included_pages[0]}.pdf' if page_files and len(page_files) == 1 and not included_sections else None

    task_id = start_task(_build_docs_pdf, included_sections, include_cover, page_files, download_name)
    return jsonify({"task_id": task_id})


def _build_docs_pdf(task_id, included_sections, include_cover, included_pages=None, download_name=None):
    """Write the task's PDF; the whole documentation is copied from the cache."""
    if not included_sections and not included_pages and ensure_docs_pdf_generated():
        filename = f"docs_manual_{task_id[:8]}.pdf"
        dest_path = os.path.join(tempfile.gettempdir(), filename)
        shutil.copy2(_docs_pdf_path(), dest_path)
        return dest_path, filename

    from documentation.pdf_generator.build_docs_pdf import _build_pdf
    filename = f"docs_custom_{task_id[:8]}.pdf"
    dest_path = os.path.join(tempfile.gettempdir(), filename)
    _build_pdf(
        included_sections=included_sections,
        include_cover=include_cover,
        output_path=Path(dest_path),
        included_pages=included_pages,
    )
    return dest_path, download_name or filename
