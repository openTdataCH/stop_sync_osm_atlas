import os
import re
import json
import sys
import importlib
import subprocess
import logging
from typing import List, Tuple, Dict, Optional
from urllib.parse import unquote

from flask import Blueprint, render_template, abort, send_from_directory, request, url_for, jsonify, send_file, redirect, current_app
from werkzeug.utils import safe_join
from backend.services.docs_stats import replace_stats_placeholders, convert_github_alerts_to_html, get_canonical_palette_html
from backend.services.repo_scanner import RepoScanner
from backend.services.request_payload import read_request_payload
import uuid
import threading
import tempfile
import shutil

from backend.services.async_export import (
    start_cleanup_thread,
    cleanup_stale_tasks,
    init_task,
    update_progress as ae_update_progress,
    set_task_status,
    complete_task,
    get_progress,
    get_completed_file,
    cancel_task as ae_cancel_task,
)

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

# Lazy-loaded RepoScanner
_repo_scanner: Optional[RepoScanner] = None

def _get_repo_scanner() -> RepoScanner:
    global _repo_scanner
    if _repo_scanner is None:
        _repo_scanner = RepoScanner(_repo_root())
    return _repo_scanner


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


def _normalize_section_key(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    text = text.rstrip('.')
    if not text:
        return None

    head = text.split('.', 1)[0].strip()
    if head.isdigit():
        return head
    return None


def _to_sections_list(value) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        sections = [_normalize_section_key(str(item)) for item in value]
        sections = [item for item in sections if item is not None]
        return sections or None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.startswith('['):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    sections = [_normalize_section_key(str(item)) for item in parsed]
                    sections = [item for item in sections if item is not None]
                    return sections or None
            except Exception:
                pass
        sections = [_normalize_section_key(item) for item in stripped.split(',')]
        sections = [item for item in sections if item is not None]
        return sections or None
    return None


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _docs_pdf_path() -> str:
    return os.path.join(_repo_root(), 'documentation', 'generated', 'stop_sync_osm_atlas_documentation.pdf')


def _existing_docs_pdf_path() -> Optional[str]:
    path = _docs_pdf_path()
    return path if os.path.exists(path) else None


def ensure_docs_pdf_generated() -> bool:
    """Ensure the docs PDF exists and is fresh relative to its sources."""
    pdf_path = _docs_pdf_path()
    existing_pdf = _existing_docs_pdf_path()
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
        if existing_pdf:
            logger.warning("Using existing docs PDF at %s", existing_pdf)
            return True
        return False

    if os.path.exists(pdf_path):
        return True

    return False


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

_MERMAID_FENCE_PATTERN = re.compile(r'```mermaid(.*?)```', re.DOTALL | re.IGNORECASE)
_MERMAID_NODE_START_PATTERN = re.compile(
    r'(?P<node_id>[A-Za-z][A-Za-z0-9_]*)'
    r'(?P<open>\[\[|\[\(|\[\{|\["|\[\'|\[|\(\(|\(|\{\{|\{)'
)
_MERMAID_EXISTING_CLICK_PATTERN = re.compile(r'(?m)^\s*click\s+([A-Za-z][A-Za-z0-9_]*)\b')
_MERMAID_NODE_CLOSERS = {
    '[[': ']]',
    '[(': ')]',
    '[{': '}]',
    '["': '"]',
    "['": "']",
    '[': ']',
    '((': '))',
    '(': ')',
    '{{': '}}',
    '{': '}',
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


def _protect_mermaid_blocks(markdown_text: str, token_prefix: str) -> Tuple[str, List[str]]:
    mermaid_blocks: List[str] = []

    def save_mermaid(match: re.Match) -> str:
        mermaid_blocks.append(match.group(0))
        return f"<!--{token_prefix}_{len(mermaid_blocks)-1}-->"

    protected = _MERMAID_FENCE_PATTERN.sub(save_mermaid, markdown_text)
    return protected, mermaid_blocks


def _restore_mermaid_blocks(markdown_text: str, token_prefix: str, mermaid_blocks: List[str]) -> str:
    pattern = re.compile(rf'<!--{token_prefix}_(\d+)-->')

    def restore_mermaid(match: re.Match) -> str:
        idx = int(match.group(1))
        return mermaid_blocks[idx]

    return pattern.sub(restore_mermaid, markdown_text)


def _protect_rendered_mermaid_divs(html: str) -> Tuple[str, List[str]]:
    mermaid_divs: List[str] = []

    def save_div(match: re.Match) -> str:
        mermaid_divs.append(match.group(0))
        return f"<!--MERMAID_HTML_{len(mermaid_divs)-1}-->"

    protected = re.sub(
        r'<div class="mermaid">.*?</div>',
        save_div,
        html,
        flags=re.DOTALL,
    )
    return protected, mermaid_divs


def _normalize_mermaid_node_label(label: str) -> str:
    normalized = label.strip().strip('"\'')
    normalized = re.split(r'\\n|<br\s*/?>', normalized, maxsplit=1, flags=re.IGNORECASE)[0]
    return normalized.strip()


def _append_mermaid_click_links(mermaid_block: str, scanner: RepoScanner, github_base: str) -> str:
    existing_click_ids = set(_MERMAID_EXISTING_CLICK_PATTERN.findall(mermaid_block))
    click_commands: List[str] = []

    for match in _MERMAID_NODE_START_PATTERN.finditer(mermaid_block):
        node_id = match.group('node_id')
        if node_id in existing_click_ids:
            continue

        opener = match.group('open')
        closer = _MERMAID_NODE_CLOSERS.get(opener)
        if closer is None:
            continue

        label_start = match.end()
        label_end = mermaid_block.find(closer, label_start)
        if label_end == -1:
            continue

        clean_label = _normalize_mermaid_node_label(mermaid_block[label_start:label_end])
        if not clean_label:
            continue

        resolved = scanner.resolve_path(clean_label)
        if not resolved:
            continue

        link = f"{github_base}{resolved}".replace(' ', '%20')
        click_commands.append(f'    click {node_id} "{link}"')
        existing_click_ids.add(node_id)

    if not click_commands:
        return mermaid_block

    fence_end = mermaid_block.rfind('```')
    if fence_end == -1:
        return mermaid_block

    body = mermaid_block[:fence_end].rstrip()
    closing_fence = mermaid_block[fence_end:]
    return f"{body}\n" + "\n".join(click_commands) + f"\n{closing_fence}"


def _auto_link_code_files(markdown_text: str) -> str:
    """Detect code file names or paths and turn them into GitHub links."""
    scanner = _get_repo_scanner()
    github_base = _github_blob_base()

    # 1. Handle standard text/backticks for paths like 'path/to/file.py' or 'file.py'
    # Pattern: words, slashes, dots, ending in .py etc.
    # Capture optional backticks so we can put them inside the link brackets: [`path.py`](url)
    ext_pattern = '|'.join(re.escape(ext.lstrip('.')) for ext in _CODE_FILE_EXTENSIONS)
    path_regex = re.compile(rf'(?<![\[\(])(`?)\b([\w\-/]+\.(?:{ext_pattern}))\b(`?)(?![\)\]])')

    def text_repl(match: re.Match) -> str:
        open_tick = match.group(1)
        path_query = match.group(2)
        close_tick = match.group(3)
        resolved = scanner.resolve_path(path_query)
        if resolved:
            link = f"{github_base}{resolved}".replace(' ', '%20')
            return f"[{open_tick}{path_query}{close_tick}]({link})"
        return match.group(0)

    protected_text, mermaid_blocks = _protect_mermaid_blocks(markdown_text, 'MERMAID_AUTOLINK')
    protected_text = path_regex.sub(text_repl, protected_text)

    processed_blocks = [
        _append_mermaid_click_links(block, scanner, github_base)
        for block in mermaid_blocks
    ]
    return _restore_mermaid_blocks(protected_text, 'MERMAID_AUTOLINK', processed_blocks)


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

    # Append non-numbered markdown files (e.g. Changelog.md) as standalone
    # entries at the bottom of the sidebar.
    for f in files:
        key = _top_level_section_key(f)
        if key is not None:
            continue  # already handled above
        title = _derive_title(f)
        slug = file_to_slug.get(f, '')
        extra_key = f"extra_{slug}"
        sections.append({
            'key': extra_key,
            'number': None,
            'root_file': f,
            'root_slug': slug,
            'root_title': title,
            'items': [],
        })

    return sections


def _read_markdown(filename: str) -> str:
    docs_dir = _get_docs_dir()
    safe_path = safe_join(docs_dir, filename)
    if not safe_path or not os.path.isfile(safe_path):
        abort(404)
    with open(safe_path, 'r', encoding='utf-8') as f:
        return f.read()






def _convert_markdown_to_html(markdown_text: str, file_to_slug: Dict[str, str]) -> str:
    # Auto-link code files (plain text and mermaid)
    markdown_text = _auto_link_code_files(markdown_text)

    markdown_text = _rewrite_repo_links_to_github(markdown_text)
    
    # Rewrite internal .md links to Flask /docs/ routes
    markdown_text = _rewrite_internal_doc_links_to_routes(markdown_text, file_to_slug)
    
    # Convert GitHub-style alerts to HTML before markdown processing
    markdown_text = convert_github_alerts_to_html(markdown_text)

    # Protect mermaid blocks from stats replacement spans
    markdown_text, mermaid_blocks = _protect_mermaid_blocks(markdown_text, 'MERMAID_BLOCK')

    # Replace stats placeholders with actual values from stats.json
    markdown_text = replace_stats_placeholders(markdown_text)

    # Restore mermaid blocks and replace stats inside them without spans
    markdown_text = _restore_mermaid_blocks(
        markdown_text,
        'MERMAID_BLOCK',
        [replace_stats_placeholders(block, no_span=True) for block in mermaid_blocks],
    )

    # Inject canonical palette grid if placeholder is present
    if '[[canonical_palette]]' in markdown_text:
        palette_html = get_canonical_palette_html()
        markdown_text = markdown_text.replace('[[canonical_palette]]', palette_html)


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

    md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'table'], hard_wrap=True)
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
        'details', 'summary', 'br'
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

    sanitized, mermaid_divs = _protect_rendered_mermaid_divs(sanitized)
    sanitized = bleach.linkify(sanitized)
    return _restore_mermaid_blocks(sanitized, 'MERMAID_HTML', mermaid_divs)


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
        return slug_to_file.get(decoded_page)

    is_partial = request.headers.get('X-Docs-Partial') == '1' or request.args.get('partial') == '1'

    # If no page specified, default to the first doc
    active_file = resolve_active_file(page)
    if not page:
        active_file = files[0]
    elif active_file is None:
        abort(404)

    active_slug = file_to_slug.get(active_file, '')

    if active_file is None:
        active_file = files[0]

    raw_markdown = _read_markdown(active_file)
    html_content = _convert_markdown_to_html(raw_markdown, file_to_slug)
    active_title = _derive_title(active_file)

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
    if active_section is None and active_file:
        # Non-numbered file (e.g. Changelog.md): use the extra_ key
        active_section = f"extra_{file_to_slug.get(active_file, '')}"

    if is_partial:
        return jsonify({
            'content_html': html_content,
            'active_file': active_file,
            'active_slug': active_slug,
            'active_section': active_section,
            'title': active_title,
            'prev_page': prev_page,
            'next_page': next_page,
            'canonical_url': url_for('docs.docs_page', page=active_slug),
        })

    from backend.blueprints.seo import site_url

    return render_template(
        'pages/docs.html',
        sections=sections,
        active_file=active_file,
        active_slug=active_slug,
        active_section=active_section,
        active_title=active_title,
        content_html=html_content,
        prev_page=prev_page,
        next_page=next_page,
        seo_canonical_url=site_url(
            url_for('docs.docs_page', page=active_slug),
        ),
    )


@docs_bp.route('/docs/assets/<path:filename>')
def docs_asset(filename: str):
    docs_dir = _get_docs_dir()
    return send_from_directory(docs_dir, filename)


@docs_bp.route('/api/docs/generate_pdf_async', methods=['POST'])
def generate_docs_pdf_async():
    start_cleanup_thread()
    cleanup_stale_tasks()
    
    data = read_request_payload(request, include_query_args=False)
    included_sections = _to_sections_list(data.get('included_sections'))  # None means all
    include_cover = _to_bool(data.get('include_cover'), default=True)
    selected_only = _to_bool(data.get('selected_only'), default=False)

    if selected_only and not included_sections:
        return jsonify({"error": "No sections selected for partial documentation export."}), 400
    
    task_id = str(uuid.uuid4())
    init_task(task_id)
    
    app_obj = current_app._get_current_object()
    
    thread = threading.Thread(
        target=_background_docs_pdf,
        args=(app_obj, task_id, included_sections, include_cover)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({"task_id": task_id})


def _background_docs_pdf(flask_app, task_id, included_sections, include_cover):
    from pathlib import Path
    
    with flask_app.app_context():
        try:
            if get_progress(task_id) is None:
                return
            set_task_status(task_id, 'processing')
            
            # Caching check if "All sections" are selected
            if not included_sections:
                if ensure_docs_pdf_generated():
                    cached_path = _existing_docs_pdf_path()
                    if cached_path:
                        filename = f"docs_manual_{task_id[:8]}.pdf"
                        temp_dir = tempfile.gettempdir()
                        dest_path = os.path.join(temp_dir, filename)
                        shutil.copy2(cached_path, dest_path)
                        complete_task(task_id, dest_path, filename)
                        ae_update_progress(task_id, 1, 1)
                        return
                        
            from documentation.pdf_generator.build_docs_pdf import _build_pdf
            filename = f"docs_custom_{task_id[:8]}.pdf"
            temp_dir = tempfile.gettempdir()
            dest_path = os.path.join(temp_dir, filename)
            
            _build_pdf(
                included_sections=included_sections, 
                include_cover=include_cover, 
                output_path=Path(dest_path)
            )
            
            complete_task(task_id, dest_path, filename)
            ae_update_progress(task_id, 1, 1)
        except Exception as e:
            set_task_status(task_id, 'error', str(e))
            flask_app.logger.error(f"Background docs PDF error: {e}")


@docs_bp.route('/api/docs/pdf_progress/<task_id>', methods=['GET'])
def get_docs_pdf_progress(task_id):
    progress = get_progress(task_id)
    if not progress:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(progress)


@docs_bp.route('/api/docs/download_pdf/<task_id>', methods=['GET'])
def download_docs_pdf_async(task_id):
    task_info = get_completed_file(task_id)
    if not task_info:
        return jsonify({"error": "PDF not found"}), 404
    
    filepath = task_info['file_path']
    filename = task_info['filename']
    
    if not os.path.exists(filepath):
        return jsonify({"error": "PDF file not found"}), 404
    
    try:
        response = send_file(
            filepath,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename,
        )

        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@docs_bp.route('/api/docs/cancel_pdf/<task_id>', methods=['POST'])
def cancel_docs_pdf(task_id):
    ae_cancel_task(task_id)
    return jsonify({"status": "cancelled"})




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
