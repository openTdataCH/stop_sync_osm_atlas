import os
import re
import json
import sys
import importlib
import subprocess
import logging
import tomllib
from functools import lru_cache
from html import unescape
from typing import List, Tuple, Dict, Optional
from urllib.parse import unquote

from flask import Blueprint, render_template, abort, send_from_directory, request, url_for, jsonify, send_file, current_app
from markupsafe import Markup
from werkzeug.utils import safe_join
from backend.services.docs_order import doc_sort_key
from backend.services.docs_stats import (
    replace_stats_placeholders, convert_github_alerts_to_html, get_canonical_palette_html, heading_slug,
)
from backend.services.quality_report import replace_quality_placeholder
from backend.services.repo_scanner import RepoScanner
from backend.services.request_payload import read_request_payload
from backend.services.site_url import site_url
from backend.version import APP_VERSION, engine_blob_base
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

# Markdown remains next to the code that owns it.  The Flask application
# assembles both trees into one reader-facing manual.
_DOC_SOURCES = {
    'app': {
        'root': 'documentation',
        'short_label': 'App',
    },
    'engine': {
        'root': 'engine/documentation',
        'short_label': 'Engine',
    },
}

# The sidebar groups. Their descriptions are on the overview page
# (documentation/0. Intro.md, "How to read this documentation"). A
# collection's owner (its source unless stated) sets its colour.
_DOC_COLLECTIONS = (
    {
        'key': 'overview',
        'label': 'Project overview',
        'source': 'app',
        'owner': 'shared',
        'sections': {'0'},
    },
    {
        'key': 'engine-inputs',
        'label': 'Engine input integrations',
        'source': 'engine',
        'sections': {'1'},
    },
    {
        'key': 'engine',
        'label': 'Matching engine core',
        'source': 'engine',
        'sections': None,
        'exclude_sections': {'1'},
    },
    {
        'key': 'app',
        'label': 'Review application & deployment',
        'source': 'app',
        'sections': None,
        'exclude_sections': {'0'},
    },
)

# Documentation numbers are scoped to the project that owns the page. Each
# source tree has its own sequential filenames so it can move to a standalone
# repository without another reorganization.
_DOC_SECTION_LABELS = {
    'engine': {
        '1': ('E1', 'Input integrations & acquisition'),
        '2': ('E2', 'Matching process'),
        '3': ('E3', 'Routes'),
        '4': ('E4', 'Problems'),
        '5': ('E5', 'Operations & performance'),
        '6': ('E6', 'Engine tests'),
    },
    'app': {
        '0': ('0.', 'Project overview'),
        '1': ('A1', 'Database & bundle import'),
        '2': ('A2', 'Web app'),
        '3': ('A3', 'Application architecture & deployment'),
        '4': ('A4', 'Tests & code quality'),
    },
}

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

    namespace = ''
    if ':' in text:
        prefix, text = text.split(':', 1)
        prefix = prefix.strip().lower()
        if prefix not in _DOC_SOURCES:
            return None
        namespace = f'{prefix}:'

    head = text.split('.', 1)[0].strip()
    if head.isdigit():
        return f'{namespace}{head}'
    if namespace and re.fullmatch(r'[a-z0-9_-]+', text):
        return f'{namespace}{text}'
    return None


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
    sections = [key for key in map(_normalize_section_key, _payload_list(value) or []) if key is not None]
    return sections or None


def _to_pages_list(value) -> Optional[List[str]]:
    """Page addresses (``exact_matching``) for a single-page export."""
    pages = [page for page in _payload_list(value) or [] if page]
    return pages or None


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _engine_root() -> str:
    """Return the standalone engine checkout or its image-build projection."""
    app_root = _repo_root()
    configured = os.getenv('ENGINE_DIR', '').strip()
    candidates = []
    if configured:
        candidates.append(
            configured if os.path.isabs(configured) else os.path.join(app_root, configured)
        )
    candidates.extend((
        os.path.join(app_root, 'engine'),
        os.path.join(os.path.dirname(app_root), 'engine'),
    ))
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, 'pyproject.toml')):
            return os.path.abspath(candidate)
    return os.path.abspath(candidates[0] if candidates else os.path.join(app_root, 'engine'))


@lru_cache(maxsize=1)
def _engine_version() -> Optional[str]:
    """Read the version without importing or installing the engine package."""
    try:
        with open(os.path.join(_engine_root(), 'pyproject.toml'), 'rb') as handle:
            version = tomllib.load(handle).get('project', {}).get('version')
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None
    return str(version).strip() if version else None


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
    generator_script = os.path.join(
        _repo_root(),
        'documentation',
        'pdf_generator',
        'build_docs_pdf.py',
    )
    stats_renderer = os.path.join(_repo_root(), 'backend', 'services', 'docs_stats.py')
    
    is_fresh = os.path.exists(pdf_path)
    if is_fresh:
        pdf_mtime = os.path.getmtime(pdf_path)
        
        # 1. Check if stats.json is newer (stats injected in placeholders)
        if os.path.exists(stats_path) and os.path.getmtime(stats_path) > pdf_mtime:
            is_fresh = False
            
        # 2. Check if any documentation source or embedded asset is newer
        if is_fresh:
            source_suffixes = {'.md', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf'}
            for source_dir in _get_docs_dirs().values():
                if not os.path.isdir(source_dir):
                    continue
                for directory, child_dirs, files in os.walk(source_dir):
                    child_dirs[:] = [name for name in child_dirs if name != 'generated']
                    for filename in files:
                        if os.path.splitext(filename)[1].lower() not in source_suffixes:
                            continue
                        src_path = os.path.join(directory, filename)
                        if os.path.getmtime(src_path) > pdf_mtime:
                            is_fresh = False
                            break
                    if not is_fresh:
                        break
                if not is_fresh:
                    break
        
        # 3. Check if the renderer implementation or print CSS is newer
        if is_fresh:
            css_path = os.path.normpath(os.path.join(docs_dir, 'pdf_generator', 'docs_print.css'))
            mermaid_config = os.path.normpath(os.path.join(
                docs_dir,
                'pdf_generator',
                'mermaid_render_config.json',
            ))
            quality_renderer = os.path.join(_repo_root(), 'backend', 'services', 'quality_report.py')
            quality_evidence = os.path.join(_repo_root(), 'quality', 'published', 'publication.json')
            for render_dependency in (generator_script, stats_renderer, quality_renderer, quality_evidence, css_path, mermaid_config):
                if (
                    os.path.exists(render_dependency)
                    and os.path.getmtime(render_dependency) > pdf_mtime
                ):
                    is_fresh = False
                    break

    if is_fresh:
        return True

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
    base = (
        os.environ.get('DOCS_GITHUB_BLOB_BASE', '').strip()
        or 'https://github.com/openTdataCH/stop_sync_osm_atlas/blob/main/'
    )
    if not base.endswith('/'):
        base += '/'
    return base


def _code_file_url(repo_path: str) -> str:
    """Return a public URL for a path in the portal's logical layout.

    Paths below ``engine/`` belong to the engine repository and link to the
    commit pinned in engine.ref; every other path belongs to this repository.
    """
    normalized = repo_path.replace(os.sep, '/')
    if normalized == 'engine' or normalized.startswith('engine/'):
        return f"{engine_blob_base()}{normalized[len('engine/'):]}".replace(' ', '%20')
    return f"{_github_blob_base()}{normalized}".replace(' ', '%20')


_CODE_FILE_EXTENSIONS = {
    '.py', '.sql', '.sh', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg',
    '.js', '.ts', '.tsx', '.jsx', '.css', '.html',
}

_MERMAID_FENCE_PATTERN = re.compile(r'```mermaid(.*?)```', re.DOTALL | re.IGNORECASE)
# Fenced code blocks, including Mermaid. The closing fence repeats the opener.
_FENCED_CODE_PATTERN = re.compile(
    r'^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n.*?^[ \t]*(?P=fence)[ \t]*$',
    re.DOTALL | re.MULTILINE,
)
_MARKDOWN_LINK_PATTERN = re.compile(r'!?\[[^\]\n]*\]\([^)\n]*\)')
_HTML_TAG_PATTERN = re.compile(r'<[^>\n]+>')
_BARE_URL_PATTERN = re.compile(r'https?://[^\s)<>\]]+')
_INLINE_CODE_PATTERN = re.compile(r'(?<!`)(?P<ticks>`+)(?!`)(?P<code>.+?)(?<!`)(?P=ticks)(?!`)')
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


def _rewrite_repo_links_to_github(markdown_text: str, current_doc: str) -> str:
    """Rewrite remaining links to repository files as public source links.

    Documentation-to-documentation links are converted to local routes first.
    Links are resolved in the portal's logical layout, where the engine tree
    lives below ``engine/``. Files of this repository become GitHub links;
    engine files link to the engine commit pinned in engine.ref.
    """

    # Match standard markdown links: [text](href "optional title").  The
    # negative lookbehind is anchored before ``[`` so image syntax is excluded.
    pattern = re.compile(r'(?<!!)\[([^\]]*)\]\(([^\s)]+)(\s+"[^"]*")?\)')
    repo_root = os.path.realpath(_repo_root())

    def repl(match: re.Match) -> str:
        label = match.group(1)
        href = match.group(2)
        title = match.group(3) or ''
        if href.startswith(('http://', 'https://', 'mailto:', '#', '/')):
            return match.group(0)

        base_part, frag = (href.split('#', 1) + [''])[:2]
        base_part, query = (base_part.split('?', 1) + [''])[:2]
        logical = os.path.normpath(
            os.path.join(os.path.dirname(current_doc), unquote(base_part))
        ).replace(os.sep, '/')
        if logical == '..' or logical.startswith('../'):
            return match.group(0)

        if logical == 'engine' or logical.startswith('engine/'):
            new_href = _code_file_url(logical)
        else:
            candidate = os.path.realpath(os.path.join(repo_root, logical))
            if not candidate.startswith(repo_root + os.sep) or not os.path.isfile(candidate):
                return match.group(0)
            new_href = _code_file_url(os.path.relpath(candidate, repo_root))
        if query:
            new_href += f'?{query}'
        if frag:
            new_href += f'#{frag}'
        return f"[{label}]({new_href}{title})"

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


def _append_mermaid_click_links(mermaid_block: str, scanner: RepoScanner) -> str:
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
        link = _code_file_url(resolved) if resolved else None
        if not link:
            continue

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


def _protect_spans(pattern: re.Pattern, text: str, store: List[str], transform=None, tag: str = 'S') -> str:
    """Replace every match with a ``tag``-scoped placeholder.

    ``transform`` may rewrite the saved text. Different stores must use
    different tags so that their placeholders can be restored independently.
    """

    def save(match: re.Match) -> str:
        store.append(transform(match) if transform else match.group(0))
        return f'{tag}{len(store) - 1}'

    return pattern.sub(save, text)


def _restore_spans(text: str, store: List[str], tag: str = 'S') -> str:
    pattern = re.compile(f'{re.escape(tag)}(\\d+)')
    # A saved span can itself contain placeholders, so restore until stable.
    while True:
        restored = pattern.sub(lambda match: store[int(match.group(1))], text)
        if restored == text:
            return restored
        text = restored


def _auto_link_code_files(markdown_text: str) -> str:
    """Link mentions of repository code files.

    Inline code that is exactly a file path (``backend/app.py``, optionally
    followed by ``::symbol``) and bare paths in prose become links. Mermaid
    nodes named after a file receive ``click`` commands. Text inside fenced
    code blocks, existing links, raw HTML and URLs is never changed.
    """
    scanner = _get_repo_scanner()
    ext_pattern = '|'.join(re.escape(ext.lstrip('.')) for ext in _CODE_FILE_EXTENSIONS)
    bare_path = re.compile(rf'(?<![\w./\\-])[\w-]+(?:/[\w.-]+)*\.(?:{ext_pattern})(?![\w/-])')
    code_path = re.compile(rf'(?P<path>[\w./-]+\.(?:{ext_pattern}))(?P<suffix>::[\w.]+(?:\(\))?)?')

    def link_for(path_query: str) -> Optional[str]:
        resolved = scanner.resolve_path(path_query)
        return _code_file_url(resolved) if resolved else None

    def fenced(match: re.Match) -> str:
        block = match.group(0)
        if match.group('info').strip().lower() == 'mermaid':
            return _append_mermaid_click_links(block, scanner)
        return block

    def inline_code(match: re.Match) -> str:
        code = match.group('code')
        target = code_path.fullmatch(code.strip())
        link = link_for(target.group('path')) if target else None
        return f'[{match.group(0)}]({link})' if link else match.group(0)

    def prose_path(match: re.Match) -> str:
        link = link_for(match.group(0))
        return f'[{match.group(0)}]({link})' if link else match.group(0)

    store: List[str] = []
    text = _protect_spans(_FENCED_CODE_PATTERN, markdown_text, store, fenced)
    text = _protect_spans(_MARKDOWN_LINK_PATTERN, text, store)
    text = _protect_spans(_HTML_TAG_PATTERN, text, store)
    text = _protect_spans(_BARE_URL_PATTERN, text, store)
    text = _protect_spans(_INLINE_CODE_PATTERN, text, store, inline_code)
    text = bare_path.sub(prose_path, text)
    return _restore_spans(text, store)


def _rewrite_internal_doc_links_to_routes(
    markdown_text: str,
    file_to_slug: Dict[str, str],
    current_doc: str,
) -> str:
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

        app_docs_prefix = (
            'https://github.com/openTdataCH/stop_sync_osm_atlas/'
            'blob/main/documentation/'
        )
        if href.startswith(app_docs_prefix):
            href = f'../../documentation/{href[len(app_docs_prefix):]}'
        elif href.startswith(('http://', 'https://', '/')):
            return match.group(0)

        # Split anchor if present
        if '#' in href:
            path_part, anchor = href.split('#', 1)
            anchor = '#' + anchor
        else:
            path_part = href
            anchor = ''

        clean_path = unquote(path_part).strip()
        candidate_file = os.path.basename(clean_path)
        if not candidate_file.lower().endswith('.md'):
            candidate_file = f"{candidate_file}.md"

        current_dir = os.path.dirname(current_doc)
        candidate_id = os.path.normpath(os.path.join(current_dir, clean_path)).replace(os.sep, '/')
        slug = file_to_slug.get(candidate_id)

        if slug is None:
            matching_slugs = {
                candidate_slug
                for doc_id, candidate_slug in file_to_slug.items()
                if os.path.basename(doc_id) == candidate_file
            }
            slug = next(iter(matching_slugs)) if len(matching_slugs) == 1 else None
        if slug is None:
            # Keep unresolved links unchanged to avoid generating broken routes.
            return match.group(0)

        # Build Flask route URL
        new_href = url_for('docs.docs_page', page=slug) + anchor
        return f'[{link_text}]({new_href})'

    return pattern.sub(repl, markdown_text)


def _get_docs_dir() -> str:
    """Return the app-owned documentation directory (legacy helper)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'documentation'))


def _get_docs_dirs() -> Dict[str, str]:
    root = _repo_root()
    return {
        'app': os.path.join(root, _DOC_SOURCES['app']['root']),
        'engine': os.path.join(_engine_root(), 'documentation'),
    }


def _doc_source_key(doc_id: str) -> str:
    normalized = doc_id.replace(os.sep, '/')
    for source_key, source in _DOC_SOURCES.items():
        prefix = source['root'].rstrip('/') + '/'
        if normalized.startswith(prefix):
            return source_key
    raise ValueError(f'Unknown documentation source for {doc_id!r}')


def list_markdown_files() -> List[str]:
    """Return stable logical IDs for app- and engine-owned Markdown pages."""
    files: List[str] = []
    for source_key in ('app', 'engine'):
        docs_dir = _get_docs_dirs()[source_key]
        if not os.path.isdir(docs_dir):
            continue
        for filename in os.listdir(docs_dir):
            if filename.lower().endswith('.md'):
                absolute = os.path.join(docs_dir, filename)
                if os.path.isfile(absolute):
                    logical_root = _DOC_SOURCES[source_key]['root'].rstrip('/')
                    files.append(f'{logical_root}/{filename}')
    files.sort(key=lambda value: (_doc_source_key(value), doc_sort_key(value)))
    return files


def _remove_numeric_prefix(stem: str) -> str:
    """Remove a leading numeric docs prefix like '2.1 ' or '5.3.2 '."""
    return re.sub(r'^\d+(?:\.\d+)*\.?\s*', '', stem).strip()


def _slugify_doc_stem(stem: str) -> str:
    """Create a URL-safe docs slug from a filename stem."""
    base = _remove_numeric_prefix(stem).lower()
    slug = re.sub(r'[^a-z0-9]+', '_', base).strip('_')
    return slug or 'doc'


def build_doc_slug_maps(files: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Build deterministic filename<->slug maps for all docs files."""
    file_to_slug: Dict[str, str] = {}
    slug_to_file: Dict[str, str] = {}

    for filename in files:
        stem = os.path.splitext(os.path.basename(filename))[0]
        base_slug = _slugify_doc_stem(stem)
        slug = base_slug
        if slug in slug_to_file and slug_to_file[slug] != filename:
            source_key = _doc_source_key(filename)
            slug = f"{source_key}_{base_slug}"
            counter = 2
            while slug in slug_to_file and slug_to_file[slug] != filename:
                slug = f"{source_key}_{base_slug}_{counter}"
                counter += 1

        file_to_slug[filename] = slug
        slug_to_file[slug] = filename

    return file_to_slug, slug_to_file


def _derive_title(filename: str) -> str:
    return os.path.splitext(os.path.basename(filename))[0].replace('_', ' ').title()


_ATX_H1_PATTERN = re.compile(r'#[ \t]+(?P<title>.+?)[ \t]*#*[ \t]*$')


@lru_cache(maxsize=256)
def _cached_page_heading(path: str, mtime: float) -> Optional[str]:
    """Return the first level-one heading of a Markdown file outside code."""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    in_fence = False
    for line in lines:
        if line.lstrip().startswith(('```', '~~~')):
            in_fence = not in_fence
            continue
        match = None if in_fence else _ATX_H1_PATTERN.fullmatch(line)
        if match:
            return match.group('title').replace('`', '').replace('*', '').strip() or None
    return None


def _page_heading(doc_id: str) -> Optional[str]:
    source_key = _doc_source_key(doc_id)
    logical_root = _DOC_SOURCES[source_key]['root'].rstrip('/')
    path = os.path.join(_get_docs_dirs()[source_key], doc_id[len(logical_root):].lstrip('/'))
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    return _cached_page_heading(path, mtime)


def _display_title(filename: str) -> str:
    """Return the project-scoped title shown in navigation and page metadata.

    Section roots use the curated labels above. Every other page uses its own
    level-one heading, so navigation and article titles always agree; the
    filename is only a fallback.
    """
    derived = _derive_title(filename)
    heading = _page_heading(filename)
    stem = os.path.splitext(os.path.basename(filename))[0]
    first_token, separator, remainder = stem.partition(' ')
    numeric_token = first_token.rstrip('.')
    source_key = _doc_source_key(filename)
    section_key = numeric_token.split('.', 1)[0]
    section_label = _DOC_SECTION_LABELS.get(source_key, {}).get(section_key)

    if not section_label:
        return heading or derived

    prefix, root_title = section_label
    if '.' not in numeric_token:
        return f'{prefix} {root_title}'.strip()

    suffix = numeric_token.split('.', 1)[1]
    subsection_prefix = f"{prefix.rstrip('.')}.{suffix}"

    if heading:
        # Drop the page's own number ("E1.2 ", "0.1 ") from its heading.
        title = re.sub(rf'^[A-Z]?{re.escape(numeric_token)}\.?\s+', '', heading, count=1)
    else:
        title = remainder.replace('_', ' ').title() if separator else ''
    return f'{subsection_prefix} {title}'.strip()


_NUMBERED_TITLE_PATTERN = re.compile(r'(?P<prefix>[A-Z]?)(?P<number>\d+(?:\.\d+)*)\.?\s+(?P<title>.+)', re.DOTALL)


def _owner_prefix(doc_id: str) -> Optional[str]:
    """Return the letter that scopes the page's number (``E``, ``A``).

    The shared project overview (section 0) has no letter.
    """
    if _top_level_section_key(doc_id) == '0':
        return None
    return _DOC_SOURCES[_doc_source_key(doc_id)]['short_label'][0]


def _split_nav_number(title: str, owner_prefix: Optional[str]) -> Tuple[Optional[str], str]:
    """Split ``E2.1 Exact matching`` into ``E.2.1`` and ``Exact matching``.

    The sidebar and the page header show the number apart from the title.
    Titles without their owner's numbering, such as the changelogs, have no
    number.
    """
    match = _NUMBERED_TITLE_PATTERN.fullmatch(title)
    if not match or match.group('prefix') != (owner_prefix or ''):
        return None, title
    number = match.group('number')
    if owner_prefix:
        number = f'{owner_prefix}.{number}'
    return number, match.group('title')


def _derive_level(filename: str) -> int:
    """Return hierarchical level inferred from numeric prefix.

    Examples:
    - "1. Foo.md" -> 1
    - "1.1 Bar.md" -> 2
    - "1.2.3 Baz.md" -> 3
    Non-numbered files -> 0
    """
    name = os.path.splitext(os.path.basename(filename))[0]
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
    name = os.path.splitext(os.path.basename(filename))[0]
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


def _group_files_by_section(
    files: List[str],
    file_to_slug: Dict[str, str],
    *,
    collection_key: str,
    source_key: str,
) -> List[Dict]:
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
        title = _display_title(f)
        nav_number, nav_title = _split_nav_number(title, _owner_prefix(f))
        if key not in sections_map:
            sections_map[key] = {
                'key': f'{collection_key}-{key}',
                'export_key': f'{source_key}:{key}',
                'number': int(key),
                'nav_number': None,
                'nav_title': None,
                'root_file': None,
                'root_slug': None,
                'root_title': None,
                'items': []
            }
        if level <= 1:
            sections_map[key]['root_file'] = f
            sections_map[key]['root_title'] = title
            sections_map[key]['root_slug'] = file_to_slug.get(f, '')
            sections_map[key]['nav_number'] = nav_number
            sections_map[key]['nav_title'] = nav_title
        else:
            sections_map[key]['items'].append({
                'file': f,
                'slug': file_to_slug.get(f, ''),
                'title': title,
                'nav_number': nav_number,
                'nav_title': nav_title,
                'level': level,
            })

    for sec in sections_map.values():
        sec['items'].sort(key=lambda it: doc_sort_key(it['file']))

    sections = sorted(sections_map.values(), key=lambda s: s['number'])

    # Append non-numbered markdown files (e.g. Changelog.md) as standalone
    # entries at the bottom of the sidebar.
    for f in files:
        key = _top_level_section_key(f)
        if key is not None:
            continue  # already handled above
        title = _display_title(f)
        slug = file_to_slug.get(f, '')
        extra_key = f"{collection_key}-extra-{slug}"
        sections.append({
            'key': extra_key,
            'export_key': f'{source_key}:extra-{slug}',
            'number': None,
            'nav_number': None,
            'nav_title': title,
            'root_file': f,
            'root_slug': slug,
            'root_title': title,
            'items': [],
        })

    return sections


def _build_doc_collections(files: List[str], file_to_slug: Dict[str, str]) -> List[Dict]:
    collections: List[Dict] = []
    for definition in _DOC_COLLECTIONS:
        selected: List[str] = []
        for doc_id in files:
            if _doc_source_key(doc_id) != definition['source']:
                continue
            section_key = _top_level_section_key(doc_id)
            included = definition.get('sections')
            excluded = definition.get('exclude_sections', set())
            if included is not None and section_key not in included:
                continue
            if section_key in excluded:
                continue
            selected.append(doc_id)

        if not selected:
            continue

        collection = {
            'owner': definition['source'],
            **definition,
            'sections': _group_files_by_section(
                selected,
                file_to_slug,
                collection_key=definition['key'],
                source_key=definition['source'],
            ),
        }
        if definition['source'] == 'engine':
            collection['version'] = _engine_version()
        elif definition['source'] == 'app':
            collection['version'] = APP_VERSION
        collections.append(collection)
    return collections


def _read_markdown(doc_id: str) -> str:
    source_key = _doc_source_key(doc_id)
    logical_root = _DOC_SOURCES[source_key]['root'].rstrip('/')
    relative_path = doc_id[len(logical_root):].lstrip('/')
    source_root = os.path.realpath(_get_docs_dirs()[source_key])
    safe_path = safe_join(source_root, relative_path)
    real_path = os.path.realpath(safe_path) if safe_path else ''
    if (
        not safe_path
        or not os.path.isfile(safe_path)
        or not real_path.startswith(source_root + os.sep)
    ):
        abort(404)
    with open(safe_path, 'r', encoding='utf-8') as f:
        return f.read()


_TABLE_BLOCK_PATTERN = re.compile(
    r'<table>\s*<thead>(?P<thead>.*?)</thead>\s*<tbody>(?P<tbody>.*?)</tbody>\s*</table>',
    re.DOTALL,
)
_TABLE_ROW_PATTERN = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
_TABLE_CELL_PATTERN = re.compile(r'<t[hd](?P<attrs>[^>]*)>(?P<body>.*?)</t[hd]>', re.DOTALL)
_TAG_STRIP_PATTERN = re.compile(r'<[^>]+>')


def _cell_visible_length(cell_html: str) -> int:
    text = _TAG_STRIP_PATTERN.sub('', cell_html)
    return len(unescape(text).strip())


def _column_widths(avg_lengths: List[float], min_pct: float = 7.0) -> List[float]:
    """Proportional column width percentages from average cell text length.

    A square-root-ish weighting keeps one long prose column from squeezing
    the others down to a sliver, and a floor keeps narrow columns (``#``)
    from disappearing. Without this, the browser's automatic table layout
    gives short code/badge columns their full preferred width and makes the
    one prose column absorb nearly all of the shrinkage, wrapping it across
    many lines while the short columns sit mostly blank.
    """
    weights = [max(length, 1) ** 0.6 for length in avg_lengths]
    total = sum(weights)
    pct = [w / total * 100 for w in weights]

    below_floor = [i for i, p in enumerate(pct) if p < min_pct]
    if below_floor and len(below_floor) < len(pct):
        reserved = min_pct * len(below_floor)
        remaining_pct = 100 - reserved
        remaining_weight = sum(w for i, w in enumerate(weights) if i not in below_floor)
        pct = [
            min_pct if i in below_floor
            else (
                weights[i] / remaining_weight * remaining_pct
                if remaining_weight
                else remaining_pct / (len(pct) - len(below_floor))
            )
            for i in range(len(pct))
        ]
    return pct


def _add_table_colgroups(html: str) -> str:
    """Give each rendered table a ``<colgroup>`` sized to its content.

    Paired with ``table-layout: fixed`` in docs.css, this replaces the
    browser's automatic column sizing (see ``_column_widths``) with
    predictable widths based on what each column actually holds.
    """

    def add_colgroup(match: re.Match) -> str:
        thead, tbody = match.group('thead'), match.group('tbody')
        header_row = _TABLE_ROW_PATTERN.search(thead)
        if not header_row:
            return match.group(0)

        header_cells = _TABLE_CELL_PATTERN.findall(header_row.group(1))
        column_count = len(header_cells)
        if column_count < 2 or any('colspan' in attrs.lower() for attrs, _ in header_cells):
            return match.group(0)

        lengths = [[_cell_visible_length(body)] for _, body in header_cells]
        for row_match in _TABLE_ROW_PATTERN.finditer(tbody):
            cells = _TABLE_CELL_PATTERN.findall(row_match.group(1))
            if len(cells) != column_count or any('colspan' in attrs.lower() for attrs, _ in cells):
                return match.group(0)
            for idx, (_, body) in enumerate(cells):
                lengths[idx].append(_cell_visible_length(body))

        avg_lengths = [sum(col) / len(col) for col in lengths]
        widths = _column_widths(avg_lengths)
        colgroup = '<colgroup>' + ''.join(f'<col width="{w:.1f}%">' for w in widths) + '</colgroup>'
        return f'<table>\n{colgroup}\n<thead>{thead}</thead>\n<tbody>{tbody}</tbody>\n</table>'

    return _TABLE_BLOCK_PATTERN.sub(add_colgroup, html)




def _convert_markdown_to_html(
    markdown_text: str,
    file_to_slug: Dict[str, str],
    current_doc: str,
) -> str:
    # Auto-link code files (plain text and mermaid)
    markdown_text = _auto_link_code_files(markdown_text)

    # Code keeps its text: the link, alert, placeholder and asset passes
    # below must not rewrite examples. Fenced blocks, Mermaid diagrams and
    # inline code are set aside until those passes are done.
    code_blocks: List[str] = []

    def keep_code_block(match: re.Match) -> str:
        if match.group('info').strip().lower() == 'mermaid':
            return match.group(0)
        code_blocks.append(match.group(0))
        return f'F{len(code_blocks) - 1}'

    markdown_text = _FENCED_CODE_PATTERN.sub(keep_code_block, markdown_text)

    # Mermaid receives statistics as plain values when it is restored.
    markdown_text, mermaid_blocks = _protect_mermaid_blocks(markdown_text, 'MERMAID_BLOCK')
    inline_code: List[str] = []
    markdown_text = _protect_spans(_INLINE_CODE_PATTERN, markdown_text, inline_code, tag='C')

    # Rewrite internal .md links to Flask /docs/ routes
    markdown_text = _rewrite_internal_doc_links_to_routes(markdown_text, file_to_slug, current_doc)

    # Remaining links to source files or non-served Markdown belong on GitHub.
    markdown_text = _rewrite_repo_links_to_github(markdown_text, current_doc)

    # The quality report can open with a warning alert, so it goes in before alert conversion.
    markdown_text = replace_quality_placeholder(markdown_text, _repo_root())

    # Convert GitHub-style alerts to HTML before markdown processing
    markdown_text = convert_github_alerts_to_html(markdown_text)

    # Replace stats placeholders with actual values from stats.json.
    markdown_text = replace_stats_placeholders(markdown_text)
    if '[[canonical_palette]]' in markdown_text:
        markdown_text = markdown_text.replace('[[canonical_palette]]', get_canonical_palette_html())

    # Rewrite repo-relative image/asset paths to the docs assets route
    # Example: ![...](images/foo.png) -> ![...](/docs/assets/images/foo.png)
    if (
        '](documentation/' in markdown_text
        or '](images/' in markdown_text
        or 'src="documentation/' in markdown_text
        or 'src="images/' in markdown_text
    ):
        source_key = _doc_source_key(current_doc)
        prefix = url_for("docs.docs_asset", filename=f"{source_key}/")

        # Markdown image/link paths
        markdown_text = markdown_text.replace('](documentation/', f']({prefix}')
        markdown_text = markdown_text.replace('](images/', f']({prefix}images/')

        # Raw HTML img tags inside markdown
        markdown_text = markdown_text.replace('src="documentation/', f'src="{prefix}')
        markdown_text = markdown_text.replace('src="images/', f'src="{prefix}images/')

    markdown_text = _restore_spans(markdown_text, inline_code, tag='C')
    markdown_text = _restore_mermaid_blocks(
        markdown_text,
        'MERMAID_BLOCK',
        [replace_stats_placeholders(block, no_span=True) for block in mermaid_blocks],
    )
    markdown_text = _restore_spans(markdown_text, code_blocks, tag='F')

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

    # A single newline is a space, as on GitHub and in the PDF, so wrapped
    # source lines do not break sentences.
    md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'table'])
    html = md(markdown_text)
    html = _add_table_colgroups(html)

    # Convert mermaid code blocks to mermaid divs for client-side rendering
    # Pattern matches: <pre><code class="language-mermaid">...</code></pre>
    html = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<div class="mermaid">{m.group(1)}</div>',
        html,
        flags=re.DOTALL
    )

    if bleach is None:
        return _add_heading_ids(_inline_svg_images(html))

    allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
        'p', 'pre', 'code', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'colgroup', 'col', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'span', 'div', 'i',
        'details', 'summary', 'br'
    ]
    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'col': ['width'],
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
    # Code is shown as written, without links. (Bleach's skip_tags option
    # would escape the entities inside it a second time.)
    code_html: List[str] = []

    def save_code(match: re.Match) -> str:
        code_html.append(match.group(0))
        return f'<!--CODE_HTML_{len(code_html) - 1}-->'

    sanitized = re.sub(r'<pre\b.*?</pre>|<code\b.*?</code>', save_code, sanitized, flags=re.DOTALL)
    sanitized = bleach.linkify(
        sanitized,
        callbacks=[*bleach.linkifier.DEFAULT_CALLBACKS, _keep_explicit_urls],
    )
    sanitized = _restore_mermaid_blocks(sanitized, 'CODE_HTML', code_html)
    sanitized = _restore_mermaid_blocks(sanitized, 'MERMAID_HTML', mermaid_divs)
    # Diagrams join the page after sanitizing: Bleach would strip the SVG.
    sanitized = _inline_svg_images(sanitized)
    return _add_heading_ids(sanitized)


_IMG_TAG_PATTERN = re.compile(r'<img\b[^>]*\bsrc="(?P<src>[^"]+)"[^>]*>')
_KIT_DIAGRAM_MARKER = '<!-- Generated by documentation/diagrams/build.py'


@lru_cache(maxsize=64)
def _cached_kit_diagram(path: str, mtime: float) -> Optional[str]:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            svg = handle.read().strip()
    except OSError:
        return None
    return svg if svg.startswith('<svg') and _KIT_DIAGRAM_MARKER in svg else None


def _inline_svg_images(html: str) -> str:
    """Replace ``<img>`` tags of kit diagrams with the SVG markup.

    A browser draws an SVG loaded through ``<img>`` as a static picture, so
    links inside it do nothing; inlined, they work. Only kit diagrams below
    an owner's ``images/`` directory are inlined: documentation/diagrams/
    build.py generates them from the repository, without styles or scripts,
    and with IDs unique per diagram. Other SVGs may carry stylesheets that
    would leak into the page, so they stay images, as on GitHub and in the
    PDF.
    """
    if '<img' not in html:
        return html
    docs_dirs = _get_docs_dirs()
    prefixes = {
        source_key: url_for('docs.docs_asset', filename=f'{source_key}/')
        for source_key in docs_dirs
    }

    def repl(match: re.Match) -> str:
        src = unquote(unescape(match.group('src')))
        for source_key, prefix in prefixes.items():
            if src.startswith(prefix):
                relative = src[len(prefix):]
                break
        else:
            return match.group(0)
        if not relative.startswith('images/') or not relative.endswith('.svg'):
            return match.group(0)
        images_dir = os.path.realpath(os.path.join(docs_dirs[source_key], 'images'))
        path = os.path.realpath(os.path.join(docs_dirs[source_key], relative))
        if not path.startswith(images_dir + os.sep):
            return match.group(0)
        try:
            svg = _cached_kit_diagram(path, os.path.getmtime(path))
        except OSError:
            return match.group(0)
        if svg is None:
            return match.group(0)
        return f'<span class="docs-diagram">{svg}</span>'

    return _IMG_TAG_PATTERN.sub(repl, html)


def _keep_explicit_urls(attrs, new=False):
    """Linkify only URLs written with a scheme.

    Bleach otherwise reads file names such as ``build.py`` or ``SourceStop.name``
    as domains, because ``.py`` and ``.name`` are top-level domains.
    """
    if new and not attrs.get('_text', '').startswith(('http://', 'https://')):
        return None
    return attrs


_SECTION_HEADING_PATTERN = re.compile(r'<h(?P<level>[2-6])>(?P<content>.*?)</h(?P=level)>', re.DOTALL)


def _add_heading_ids(html: str) -> str:
    """Give section headings stable ``id`` anchors (duplicates get ``-1``…)."""
    seen: Dict[str, int] = {}

    def replace(match: re.Match) -> str:
        slug = heading_slug(match.group('content')) or 'section'
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchor = slug if count == 0 else f'{slug}-{count}'
        level = match.group('level')
        return f'<h{level} id="{anchor}">{match.group("content")}</h{level}>'

    return _SECTION_HEADING_PATTERN.sub(replace, html)


# Pages that describe another page of the site link to it from their header,
# next to the PDF export.
_PAGE_HEADER_LINKS = {
    'documentation/4.3 Code Quality.md': (
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
        number, title_html = _split_nav_number(match.group('title').strip(), _owner_prefix(doc_id))
        html = html[match.end():]
    title_text = Markup(title_html).striptags() if title_html else _display_title(doc_id)
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
    html_content = _convert_markdown_to_html(raw_markdown, file_to_slug, active_file)
    active_title = _display_title(active_file)

    collections = _build_doc_collections(files, file_to_slug)
    sections = [
        section
        for collection in collections
        for section in collection['sections']
    ]
    # Build an ordered flat list for prev/next navigation
    ordered_pages: List[Dict[str, str]] = []
    for sec in sections:
        if sec.get('root_file'):
            ordered_pages.append({
                'file': sec['root_file'],
                'slug': file_to_slug.get(sec['root_file'], ''),
                'title': sec.get('root_title') or _display_title(sec['root_file']),
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

    active_section = None
    active_collection = None
    for collection in collections:
        for section in collection['sections']:
            section_files = [section.get('root_file')]
            section_files.extend(item['file'] for item in section['items'])
            if active_file in section_files:
                active_section = section['key']
                active_collection = collection
                break
        if active_collection:
            break

    page_header, html_content = _page_header(
        html_content, active_file, active_collection, active_slug, active_section,
    )

    if is_partial:
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
        sections=sections,
        active_file=active_file,
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
    if not separator or source_key not in _DOC_SOURCES:
        # Preserve old app-owned asset URLs during the transition.
        source_key = 'app'
        relative_path = filename
    return send_from_directory(_get_docs_dirs()[source_key], relative_path)


@docs_bp.route('/api/docs/generate_pdf_async', methods=['POST'])
def generate_docs_pdf_async():
    start_cleanup_thread()
    cleanup_stale_tasks()
    
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
    
    task_id = str(uuid.uuid4())
    init_task(task_id)
    
    app_obj = current_app._get_current_object()
    
    thread = threading.Thread(
        target=_background_docs_pdf,
        args=(app_obj, task_id, included_sections, include_cover, page_files, download_name)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({"task_id": task_id})


def _background_docs_pdf(flask_app, task_id, included_sections, include_cover, included_pages=None, download_name=None):
    from pathlib import Path
    
    with flask_app.app_context():
        try:
            if get_progress(task_id) is None:
                return
            set_task_status(task_id, 'processing')
            
            # Caching check if "All sections" are selected
            if not included_sections and not included_pages:
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
                output_path=Path(dest_path),
                included_pages=included_pages,
            )
            
            complete_task(task_id, dest_path, download_name or filename)
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
