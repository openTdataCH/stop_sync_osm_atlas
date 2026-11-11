"""Markdown to safe HTML for the documentation portal.

Links to code files, pages and source files are resolved, placeholders are
filled, Mistune renders the page and Bleach keeps only allowed tags. Code
blocks and inline code are shown exactly as written.
"""
import os
import re
from functools import lru_cache
from html import unescape
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import bleach
import mistune
from bleach.css_sanitizer import CSSSanitizer
from flask import url_for

from backend.services.docs_sources import code_file_url, doc_source_key, docs_dirs, rewrite_doc_links, rewrite_repo_links
from backend.services.docs_stats import (
    convert_github_alerts_to_html, get_canonical_palette_html, heading_slug, replace_stats_placeholders,
)
from backend.services.repo_scanner import RepoScanner
from backend.version import APP_ROOT, engine_dir


@lru_cache(maxsize=1)
def _get_repo_scanner() -> RepoScanner:
    return RepoScanner(str(APP_ROOT), str(engine_dir()))


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
        link = code_file_url(resolved) if resolved else None
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


def auto_link_code_files(markdown_text: str) -> str:
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
        return code_file_url(resolved) if resolved else None

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


def convert_markdown_to_html(
    markdown_text: str,
    file_to_slug: Dict[str, str],
    current_doc: str,
) -> str:
    # Auto-link code files (plain text and mermaid)
    markdown_text = auto_link_code_files(markdown_text)

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
    markdown_text = rewrite_doc_links(
        markdown_text, file_to_slug, current_doc,
        lambda slug, fragment: url_for('docs.docs_page', page=slug) + (f'#{fragment}' if fragment else ''),
    )

    # Remaining links to source files or non-served Markdown belong on GitHub.
    markdown_text = rewrite_repo_links(markdown_text, current_doc)

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
        source_key = doc_source_key(current_doc)
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

    html = _render_card_lists(html)

    allowed_tags = list(bleach.sanitizer.ALLOWED_TAGS) + [
        'p', 'pre', 'code', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'colgroup', 'col', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'span', 'div', 'i',
        'details', 'summary', 'br'
    ]
    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'col': ['width'],
        'img': ['src', 'alt', 'title'],
        'a': ['href', 'title', 'name', 'target', 'rel', 'class'],
        'span': ['class', 'data-stat-key', 'title', 'style'],
        'div': ['class', 'style'],
        'i': ['class'],
        'details': ['class', 'open'],
        'summary': ['class']
    }
    sanitized = bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        css_sanitizer=CSSSanitizer(allowed_css_properties=['background-color']),
    )

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


# A list whose every item reads
#   - <i class="fas fa-map"></i> **Map** · [Title](page.md#section) — One sentence.
# becomes a grid of cards. GitHub and the PDF show the same list as written.
_CARD_ITEM_PATTERN = re.compile(
    r'<li>\s*<i class="(?P<icon>fa[srb]? fa-[\w-]+)"></i>\s*<strong>(?P<tag>[^<]+)</strong>\s*·\s*'
    r'<a href="(?P<href>[^"]+)">(?P<title>[^<]+)</a>\s*—\s*(?P<text>(?:(?!<a\b|</li>).)+?)\s*</li>',
    re.DOTALL,
)


def _render_card_lists(html: str) -> str:
    def card(match: re.Match) -> str:
        return (
            f'<a class="docs-card" href="{match["href"]}">'
            f'<span class="docs-card-head"><span class="docs-card-icon"><i class="{match["icon"]}"></i></span>'
            f'<span class="docs-card-tag">{match["tag"]}</span></span>'
            f'<span class="docs-card-title">{match["title"]}</span>'
            f'<span class="docs-card-text">{match["text"]}</span>'
            '<span class="docs-card-more">Read <i class="fas fa-arrow-right"></i></span></a>'
        )

    def card_list(match: re.Match) -> str:
        items = re.findall(r'<li>.*?</li>', match.group(1), re.DOTALL)
        cards = [_CARD_ITEM_PATTERN.fullmatch(item.strip()) for item in items]
        if not cards or not all(cards):
            return match.group(0)
        return '<div class="docs-cards">' + ''.join(card(c) for c in cards) + '</div>'

    return re.sub(r'<ul>\s*(.*?)\s*</ul>', card_list, html, flags=re.DOTALL)


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
    dirs = docs_dirs()
    prefixes = {
        source_key: url_for('docs.docs_asset', filename=f'{source_key}/')
        for source_key in dirs
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
        images_dir = os.path.realpath(os.path.join(dirs[source_key], 'images'))
        path = os.path.realpath(os.path.join(dirs[source_key], relative))
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
