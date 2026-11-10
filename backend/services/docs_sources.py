"""Where the documentation pages come from: their files, addresses, titles,
numbers and sidebar collections, and the links between them.

The portal (``backend/blueprints/docs.py``) and the PDF generator
(``documentation/pdf_generator/build_docs_pdf.py``) both read the pages
through this module, so they agree on order, section keys and links.
"""
import os
import re
import tomllib
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

from backend.services.docs_order import doc_sort_key
from backend.version import APP_ROOT, APP_VERSION, engine_blob_base, engine_dir

# Markdown remains next to the code that owns it.  The Flask application
# assembles both trees into one reader-facing manual.
DOC_SOURCES = {
    'app': {
        'root': 'documentation',
        'short_label': 'App',
    },
    'engine': {
        'root': 'engine/documentation',
        'short_label': 'Engine',
    },
}


# The sidebar groups: the user guide, then the two projects for developers.
# The start page (documentation/0. Intro.md) introduces them.
# A collection's owner (its source unless stated) sets its colour.
_DOC_COLLECTIONS = (
    {
        'key': 'overview',
        'label': 'User guide',
        'audience': 'For users',
        'source': 'app',
        'owner': 'shared',
        'sections': {'0'},
    },
    {
        'key': 'engine',
        'label': 'Matching engine',
        'audience': 'For developers',
        'source': 'engine',
        'sections': None,
    },
    {
        'key': 'app',
        'label': 'Review application',
        'audience': 'For developers',
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
        '0': ('0.', 'User guide'),
        '1': ('A1', 'Database & bundle import'),
        '2': ('A2', 'Web app'),
        '3': ('A3', 'Application architecture & deployment'),
        '4': ('A4', 'Tests & code quality'),
    },
}


def normalize_section_key(value) -> Optional[str]:
    """``engine:2``, ``app:extra-changelog`` or a bare ``2`` from user input; None if invalid."""
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
        if prefix not in DOC_SOURCES:
            return None
        namespace = f'{prefix}:'

    head = text.split('.', 1)[0].strip()
    if head.isdigit():
        return f'{namespace}{head}'
    if namespace and re.fullmatch(r'[a-z0-9_-]+', text):
        return f'{namespace}{text}'
    return None


@lru_cache(maxsize=1)
def engine_version() -> Optional[str]:
    """Read the version without importing or installing the engine package."""
    try:
        with open(engine_dir() / 'pyproject.toml', 'rb') as handle:
            version = tomllib.load(handle).get('project', {}).get('version')
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None
    return str(version).strip() if version else None


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


def code_file_url(repo_path: str) -> str:
    """Return a public URL for a path in the portal's logical layout.

    Paths below ``engine/`` belong to the engine repository and link to the
    commit pinned in engine.ref; every other path belongs to this repository.
    """
    normalized = repo_path.replace(os.sep, '/')
    if normalized == 'engine' or normalized.startswith('engine/'):
        return f"{engine_blob_base()}{normalized[len('engine/'):]}".replace(' ', '%20')
    return f"{_github_blob_base()}{normalized}".replace(' ', '%20')


def rewrite_repo_links(markdown_text: str, current_doc: str) -> str:
    """Rewrite remaining links to repository files as public source links.

    Documentation-to-documentation links are rewritten first
    (``rewrite_doc_links``). Links are resolved in the portal's logical
    layout, where the engine tree lives below ``engine/``. Files of this
    repository become GitHub links; engine files link to the engine commit
    pinned in engine.ref.
    """

    # Match standard markdown links: [text](href "optional title").  The
    # negative lookbehind is anchored before ``[`` so image syntax is excluded.
    pattern = re.compile(r'(?<!!)\[([^\]]*)\]\(([^\s)]+)(\s+"[^"]*")?\)')
    repo_root = os.path.realpath(APP_ROOT)

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
            new_href = code_file_url(logical)
        else:
            candidate = os.path.realpath(os.path.join(repo_root, logical))
            if not candidate.startswith(repo_root + os.sep) or not os.path.isfile(candidate):
                return match.group(0)
            new_href = code_file_url(os.path.relpath(candidate, repo_root))
        if query:
            new_href += f'?{query}'
        if frag:
            new_href += f'#{frag}'
        return f"[{label}]({new_href}{title})"

    return pattern.sub(repl, markdown_text)


def rewrite_doc_links(
    markdown_text: str,
    file_to_slug: Dict[str, str],
    current_doc: str,
    href_for: Callable[[str, str], Optional[str]],
) -> str:
    """Point relative .md links at the pages they name.

    ``href_for(slug, fragment)`` gives the new address: a /docs/ route in
    the portal, an anchor in the PDF. Links it returns None for, and links
    to files that are not pages, stay unchanged.
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

        path_part, _, fragment = href.partition('#')
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
        # Keep unresolved links unchanged to avoid generating broken routes.
        new_href = href_for(slug, fragment) if slug is not None else None
        return f'[{link_text}]({new_href})' if new_href else match.group(0)

    return pattern.sub(repl, markdown_text)


def docs_dirs() -> Dict[str, str]:
    return {
        'app': str(APP_ROOT / DOC_SOURCES['app']['root']),
        'engine': str(engine_dir() / 'documentation'),
    }


def doc_source_key(doc_id: str) -> str:
    normalized = doc_id.replace(os.sep, '/')
    for source_key, source in DOC_SOURCES.items():
        prefix = source['root'].rstrip('/') + '/'
        if normalized.startswith(prefix):
            return source_key
    raise ValueError(f'Unknown documentation source for {doc_id!r}')


def list_markdown_files() -> List[str]:
    """Return stable logical IDs for app- and engine-owned Markdown pages."""
    files: List[str] = []
    for source_key in ('app', 'engine'):
        docs_dir = docs_dirs()[source_key]
        if not os.path.isdir(docs_dir):
            continue
        for filename in os.listdir(docs_dir):
            if filename.lower().endswith('.md'):
                absolute = os.path.join(docs_dir, filename)
                if os.path.isfile(absolute):
                    logical_root = DOC_SOURCES[source_key]['root'].rstrip('/')
                    files.append(f'{logical_root}/{filename}')
    files.sort(key=lambda value: (doc_source_key(value), doc_sort_key(value)))
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
            source_key = doc_source_key(filename)
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
    try:
        path = source_path(doc_id)
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    return _cached_page_heading(path, mtime)


def display_title(filename: str) -> str:
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
    source_key = doc_source_key(filename)
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


def owner_prefix(doc_id: str) -> Optional[str]:
    """Return the letter that scopes the page's number (``E``, ``A``).

    The shared user guide (section 0) has no letter.
    """
    if top_level_section_key(doc_id) == '0':
        return None
    return DOC_SOURCES[doc_source_key(doc_id)]['short_label'][0]


def split_nav_number(title: str, owner_prefix: Optional[str]) -> Tuple[Optional[str], str]:
    """Split ``E2.1 Reference matching`` into ``E.2.1`` and ``Reference matching``.

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


def top_level_section_key(filename: str) -> Optional[str]:
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
        key = top_level_section_key(f)
        if key is None:
            continue
        level = _derive_level(f)
        title = display_title(f)
        nav_number, nav_title = split_nav_number(title, owner_prefix(f))
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
        key = top_level_section_key(f)
        if key is not None:
            continue  # already handled above
        title = display_title(f)
        slug = file_to_slug.get(f, '')
        extra_key = f"{collection_key}-extra-{slug}"
        # The owner already tells equal names apart: engine:extra-changelog.
        stem = os.path.splitext(os.path.basename(f))[0]
        sections.append({
            'key': extra_key,
            'export_key': f'{source_key}:extra-{_slugify_doc_stem(stem)}',
            'number': None,
            'nav_number': None,
            'nav_title': title,
            'root_file': f,
            'root_slug': slug,
            'root_title': title,
            'items': [],
        })

    return sections


def build_doc_collections(files: List[str], file_to_slug: Dict[str, str]) -> List[Dict]:
    collections: List[Dict] = []
    for definition in _DOC_COLLECTIONS:
        selected: List[str] = []
        for doc_id in files:
            if doc_source_key(doc_id) != definition['source']:
                continue
            section_key = top_level_section_key(doc_id)
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
            collection['version'] = engine_version()
        elif definition['source'] == 'app':
            collection['version'] = APP_VERSION
        collections.append(collection)
    return collections


def reading_order(collections: List[Dict]) -> List[Tuple[Dict, Dict, str]]:
    """Every page as ``(collection, section, logical path)``, in the order of the sidebar."""
    return [
        (collection, section, doc_id)
        for collection in collections
        for section in collection['sections']
        for doc_id in ([section['root_file']] if section['root_file'] else []) + [item['file'] for item in section['items']]
    ]


def source_path(doc_id: str) -> str:
    """The file of a page, given its logical path such as ``engine/documentation/2. Matching process.md``.

    Raises FileNotFoundError for a missing page or a path outside its tree.
    """
    source_key = doc_source_key(doc_id)
    logical_root = DOC_SOURCES[source_key]['root'].rstrip('/')
    source_root = os.path.realpath(docs_dirs()[source_key])
    path = os.path.realpath(os.path.join(source_root, doc_id[len(logical_root):].lstrip('/')))
    if not path.startswith(source_root + os.sep) or not os.path.isfile(path):
        raise FileNotFoundError(doc_id)
    return path


def read_markdown(doc_id: str) -> str:
    with open(source_path(doc_id), 'r', encoding='utf-8') as handle:
        return handle.read()
