from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import textwrap
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

import mistune
from weasyprint import HTML, CSS

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The pages, their order, section keys and links are the portal's.
from backend.services.docs_sources import (
    build_doc_collections, build_doc_slug_maps, list_markdown_files, normalize_section_key, reading_order,
    rewrite_doc_links, rewrite_repo_links, source_path,
)
from backend.services.docs_stats import (
    load_stats_for_docs, replace_stats_placeholders, convert_github_alerts_to_html, get_canonical_palette_html,
    heading_slug,
)
from backend.services.quality_report import replace_quality_placeholder


DOCS_DIR = REPO_ROOT / 'documentation'
OUTPUT_DIR = DOCS_DIR / 'generated'
DIAGRAMS_DIR = OUTPUT_DIR / 'diagrams'
STYLE_PATH = DOCS_DIR / 'pdf_generator' / 'docs_print.css'
COMBINED_MD_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.md'
OUTPUT_HTML_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.html'
OUTPUT_PDF_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_documentation.pdf'
SVG_NS = 'http://www.w3.org/2000/svg'
XHTML_NS = 'http://www.w3.org/1999/xhtml'
MERMAID_CONFIG_PATH = DOCS_DIR / 'pdf_generator' / 'mermaid_render_config.json'
MERMAID_RENDER_CONFIG = json.loads(MERMAID_CONFIG_PATH.read_text(encoding='utf-8'))
MERMAID_RENDER_CACHE_VERSION = MERMAID_RENDER_CONFIG['cacheVersion']
MERMAID_INIT_DIRECTIVE = MERMAID_RENDER_CONFIG['initDirective']

ET.register_namespace('', SVG_NS)


def _parse_svg_number(value: str | None) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    text = re.sub(r'[^0-9+\-.eE]', '', text)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _sorted_docs(included_sections: list[str] | None = None, included_pages: list[str] | None = None) -> list[str]:
    """Documentation pages (logical paths) in sidebar order, optionally only the selected ones.

    Sections are the sidebar's owner-qualified keys (``engine:2``,
    ``engine:extra-changelog``), or a bare number for both owners; pages are
    logical paths such as ``engine/documentation/2.1 Reference matching.md``.
    """
    files = list_markdown_files()
    collections = build_doc_collections(files, build_doc_slug_maps(files)[0])
    everything = included_sections is None and included_pages is None
    keys = {normalize_section_key(section) for section in included_sections or ()}
    pages = set(included_pages or ())
    return [
        doc_id for _, section, doc_id in reading_order(collections)
        if everything or doc_id in pages or section['export_key'] in keys or str(section['number']) in keys
    ]


def _section_anchor(doc_anchor: str, fragment: str) -> str:
    """Anchor of a heading inside one document of the combined PDF."""
    return f'{doc_anchor}--{fragment}' if fragment else doc_anchor


def _rewrite_same_page_links(content: str, doc_anchor: str) -> str:
    """Point ``[text](#section)`` at that document's heading in the bundle."""
    return re.sub(
        r'(?<!!)(\[[^\]]+\])\(#([^)\s]+)\)',
        lambda match: f'{match.group(1)}(#{_section_anchor(doc_anchor, match.group(2))})',
        content,
    )


def _unlink_site_pages(content: str) -> str:
    """Keep only the words of links to pages of the web app, such as /quality.

    They resolve against whichever site serves the portal; a PDF has no site.
    """
    return re.sub(r'(?<!!)\[([^\]]*)\]\(/(?!/)[^)]*\)', r'\1', content)


def _extract_foreign_object_lines(foreign_object: ET.Element) -> list[str]:
    lines: list[str] = []
    current_line_parts: list[str] = []

    def flush_line() -> None:
        text = ''.join(current_line_parts).strip()
        if text:
            lines.append(text)
        current_line_parts.clear()

    def walk(node: ET.Element) -> None:
        tag = node.tag.rsplit('}', 1)[-1]
        if node.text:
            current_line_parts.append(node.text)
        if tag == 'br':
            flush_line()
        for child in list(node):
            walk(child)
            if child.tail:
                current_line_parts.append(child.tail)
        if tag == 'p':
            flush_line()

    walk(foreign_object)
    flush_line()
    return [line for line in lines if line]


def _fit_svg_text_lines(
    lines: list[str],
    width: float,
    height: float,
) -> tuple[list[str], float]:
    """Wrap SVG fallback labels and choose the largest size that fits."""
    normalized = [' '.join(line.split()) for line in lines if line.strip()]
    if not normalized or width <= 0 or height <= 0:
        return normalized, 15.0

    available_width = max(width - 8, 1)
    available_height = max(height - 4, 1)
    fitted_lines = normalized

    for font_size in range(15, 7, -1):
        max_chars = max(1, int(available_width / (font_size * 0.56)))
        wrapped: list[str] = []
        for line in normalized:
            wrapped.extend(textwrap.wrap(
                line,
                width=max_chars,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [''])

        fitted_lines = wrapped
        if len(wrapped) * font_size * 1.2 <= available_height:
            return wrapped, float(font_size)

    return fitted_lines, 8.0


def _convert_foreign_objects_to_svg_text(svg: str) -> str:
    svg = svg.replace('&nbsp;', ' ')
    svg = re.sub(
        r'&([a-zA-Z][a-zA-Z0-9]+);',
        lambda match: html.unescape(match.group(0)) if match.group(1) not in {'amp', 'lt', 'gt', 'quot', 'apos'} else match.group(0),
        svg,
    )
    root = ET.fromstring(svg)

    for parent in root.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag != f'{{{SVG_NS}}}foreignObject':
                continue

            x = _parse_svg_number(child.attrib.get('x'))
            y = _parse_svg_number(child.attrib.get('y'))
            width = _parse_svg_number(child.attrib.get('width'))
            height = _parse_svg_number(child.attrib.get('height'))
            lines = _extract_foreign_object_lines(child)
            if not lines:
                parent.remove(child)
                continue
            lines, font_size = _fit_svg_text_lines(lines, width, height)

            text_elem = ET.Element(f'{{{SVG_NS}}}text', {
                'x': f'{x + (width / 2):.3f}',
                'y': f'{y + (height / 2):.3f}',
                'text-anchor': 'middle',
                'dominant-baseline': 'middle',
                'font-family': 'DejaVu Sans,Trebuchet MS,Verdana,Arial,sans-serif',
                'font-size': f'{font_size:g}',
                'fill': '#1a1a1a',
            })

            line_count = len(lines)
            if line_count == 1:
                text_elem.text = lines[0]
            else:
                for line_index, line in enumerate(lines):
                    tspan = ET.SubElement(text_elem, f'{{{SVG_NS}}}tspan', {
                        'x': f'{x + (width / 2):.3f}',
                    })
                    if line_index == 0:
                        baseline_offset = -0.6 * (line_count - 1)
                        tspan.set('dy', f'{baseline_offset:.3f}em')
                    else:
                        tspan.set('dy', '1.2em')
                    tspan.text = line

            parent.remove(child)
            parent.insert(index, text_elem)

    return ET.tostring(root, encoding='unicode')


def _ensure_svg_text_visibility(svg: str) -> str:
    root = ET.fromstring(svg)

    for elem in root.iter():
        local_name = elem.tag.rsplit('}', 1)[-1]
        if local_name != 'text':
            continue

        if 'fill' in elem.attrib:
            continue

        style = elem.attrib.get('style', '')
        if 'fill:' in style:
            continue

        elem.set('fill', '#1a1a1a')

    return ET.tostring(root, encoding='unicode')


def _prepare_svg_asset_for_pdf(source_path: Path) -> Path:
    raw_svg = source_path.read_text(encoding='utf-8')
    converted_svg = _convert_foreign_objects_to_svg_text(raw_svg)
    converted_svg = _ensure_svg_text_visibility(converted_svg)

    digest = hashlib.sha256(converted_svg.encode('utf-8')).hexdigest()[:16]
    output_path = DIAGRAMS_DIR / f'asset-{digest}.svg'
    if not output_path.exists():
        output_path.write_text(converted_svg, encoding='utf-8')
    return output_path


def _resolve_local_asset_path(asset_ref: str, source_dir: Path | None = None) -> Path | None:
    parsed = urlparse(asset_ref)
    decoded = unquote(parsed.path if parsed.scheme == 'file' else asset_ref)

    candidates: list[Path] = []
    if source_dir is not None:
        candidates.append((source_dir / decoded).resolve())
    candidates.append((DOCS_DIR / decoded).resolve())
    candidates.append((REPO_ROOT / decoded).resolve())

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _rewrite_svg_img_tags_in_html(html_content: str, source_dir: Path | None = None) -> str:
    pattern = re.compile(r'(<img\b[^>]*?\bsrc=["\'])([^"\']+)(["\'])', flags=re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        src = match.group(2)
        if src.startswith(('http://', 'https://', 'data:')):
            return match.group(0)

        base_src = src.split('#', 1)[0].split('?', 1)[0]
        if not base_src.lower().endswith('.svg'):
            return match.group(0)

        resolved = _resolve_local_asset_path(base_src, source_dir=source_dir)
        if resolved is None:
            return match.group(0)

        try:
            svg_path = _prepare_svg_asset_for_pdf(resolved)
        except Exception:
            return match.group(0)

        return f'{match.group(1)}{svg_path.as_uri()}{match.group(3)}'

    return pattern.sub(replace, html_content)


def _rewrite_markdown_asset_paths(content: str, source_dir: Path) -> str:
    pattern = re.compile(r'!\[([^\]]*)\]\(([^\s)]+)\)')

    def replace(match: re.Match[str]) -> str:
        asset_ref = match.group(2)
        if asset_ref.startswith(('http://', 'https://', 'data:', 'file:', '/')):
            return match.group(0)
        resolved = _resolve_local_asset_path(asset_ref, source_dir=source_dir)
        if resolved is None:
            return match.group(0)
        return (
            f'<img src="{escape(resolved.as_uri(), quote=True)}" '
            f'alt="{escape(match.group(1), quote=True)}" />'
        )

    return pattern.sub(replace, content)


def _render_mermaid_to_local_svg(diagram_source: str) -> Path:
    normalized_source = diagram_source.strip() + '\n'
    if "%%{init:" not in normalized_source:
        normalized_source = f'{MERMAID_INIT_DIRECTIVE}\n{normalized_source}'

    cache_input = f'{MERMAID_RENDER_CACHE_VERSION}\0{normalized_source}'
    digest = hashlib.sha256(cache_input.encode('utf-8')).hexdigest()[:16]
    output_path = DIAGRAMS_DIR / f'mermaid-{digest}.svg'
    if output_path.exists():
        return output_path

    raise RuntimeError(
        'A pre-rendered Mermaid asset is missing. Run '
        '`npm run docs:render-mermaid` before building the PDF.'
    )


def _rewrite_mermaid_blocks(content: str) -> str:
    pattern = re.compile(r'```mermaid\n(.*?)```', re.DOTALL)

    def replace(match: re.Match[str]) -> str:
        diagram_source = match.group(1).strip('\n')
        svg_path = _render_mermaid_to_local_svg(diagram_source)
        return (
            '\n<div class="mermaid-figure">\n'
            f'<img src="{svg_path.as_uri()}" alt="Mermaid diagram" />\n'
            '</div>\n'
        )

    return pattern.sub(replace, content)


def _process_markdown_headers(content: str, filename: str) -> str:
    name = Path(filename).stem
    first_token = name.split(' ')[0] if ' ' in name else name
    prefix = first_token.rstrip('.')
    
    if not prefix or not prefix[0].isdigit() or not all(ch.isdigit() or ch == '.' for ch in prefix):
        return content
        
    segments = [seg for seg in prefix.split('.') if seg]
    if not segments or not all(seg.isdigit() for seg in segments):
        return content
        
    level = len(segments)
    shift = level - 1
    
    lines = content.split('\n')
    processed_lines = []
    first_heading_processed = False
    
    in_fence = False
    for line in lines:
        if line.lstrip().startswith(('```', '~~~')):
            in_fence = not in_fence
        match = None if in_fence else re.match(r'^(#+)\s+(.*)$', line)
        if match:
            hashes = match.group(1)
            title = match.group(2)

            if shift > 0:
                hashes += '#' * shift

            if not first_heading_processed:
                # Headings already carry their owner-scoped number ("E1.2 …",
                # "A3 …"); only add the plain number when it is missing.
                if not re.match(rf'[A-Z]?{re.escape(prefix)}(?![\d.])|[A-Z]?{re.escape(prefix)}\.', title):
                    title = f"{prefix} {title}"
                first_heading_processed = True
                
            processed_lines.append(f"{hashes} {title}")
        else:
            processed_lines.append(line)
            
    return '\n'.join(processed_lines)


def _prepare_document(doc_ids: list[str], include_cover: bool = True) -> str:
    """One Markdown document of the given pages; each starts at anchor ``doc-<address>``."""
    file_to_slug, _ = build_doc_slug_maps(list_markdown_files())
    included = {file_to_slug[doc_id] for doc_id in doc_ids}

    def page_anchor(slug: str, fragment: str) -> str | None:
        # Links to pages left out of this PDF go to GitHub instead.
        return f'#{_section_anchor(f"doc-{slug}", fragment)}' if slug in included else None

    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    stats = load_stats_for_docs()

    parts = []
    
    if include_cover:
        parts.extend([
            '<div class="title-page">',
            '<div class="title-page__eyebrow">Stop Sync OSM Atlas</div>',
            '<div class="title-page__title">Documentation Bundle</div>',
            f'<div class="title-page__deck">A print-oriented export of the repository documentation. &nbsp; <small>({generated_at})</small></div>',
            '</div>',
            '<div class="page-break"></div>',
            '',
        ])

    for doc_id in doc_ids:
        doc_anchor = f'doc-{file_to_slug[doc_id]}'
        doc_path = Path(source_path(doc_id))
        parts.extend([
            f'<div id="{doc_anchor}" class="doc-anchor"></div>',
            '',
        ])

        content = doc_path.read_text(encoding='utf-8')
        
        mermaid_blocks = []
        def save_mermaid(match: re.Match[str]) -> str:
            mermaid_blocks.append(match.group(0))
            return f"<!--MERMAID_BLOCK_{len(mermaid_blocks)-1}-->"

        content = re.sub(r'```mermaid.*?```', save_mermaid, content, flags=re.DOTALL)

        # Code shows placeholders, links and paths literally; rewrite only prose.
        literal_code = []

        def save_code(match: re.Match[str]) -> str:
            literal_code.append(match.group(0))
            return f'{len(literal_code) - 1}'

        content = re.sub(r'^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$', save_code, content,
                         flags=re.DOTALL | re.MULTILINE)
        content = re.sub(r'(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)', save_code, content)
        content = replace_stats_placeholders(content, stats, html_escape=True)
        content = replace_quality_placeholder(content, REPO_ROOT)
        if '[[canonical_palette]]' in content:
            content = content.replace('[[canonical_palette]]', get_canonical_palette_html())
        content = _rewrite_same_page_links(content, doc_anchor)
        content = rewrite_doc_links(content, file_to_slug, doc_id, page_anchor)
        content = rewrite_repo_links(content, doc_id)
        content = _unlink_site_pages(content)
        content = convert_github_alerts_to_html(content)
            
        def restore_mermaid(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            block = mermaid_blocks[idx]
            return replace_stats_placeholders(block, stats, html_escape=True, no_span=True)
            
        content = re.sub(r'<!--MERMAID_BLOCK_(\d+)-->', restore_mermaid, content)
        
        content = _rewrite_mermaid_blocks(content)
        content = _rewrite_markdown_asset_paths(content, doc_path.parent)
        content = re.sub('(\\d+)', lambda match: literal_code[int(match.group(1))], content)
        content = _process_markdown_headers(content, doc_path.name)
        parts.append(content.strip())
        parts.append('')

    return '\n'.join(parts)


def _add_section_heading_ids(body_html: str) -> str:
    """Give headings ``<document anchor>--<GitHub slug>`` ids in the bundle.

    Each source page starts with its ``doc-anchor`` marker; links rewritten by
    ``_section_anchor`` point at these ids.
    """
    token = re.compile(
        r'<div id="(?P<doc>doc-[^"]+)" class="doc-anchor"></div>'
        r'|<h(?P<level>[1-6])>(?P<content>.*?)</h(?P=level)>',
        re.DOTALL,
    )
    current = {'doc': None, 'seen': {}}

    def replace(match: re.Match[str]) -> str:
        if match.group('doc'):
            current['doc'] = match.group('doc')
            current['seen'] = {}
            return match.group(0)
        if current['doc'] is None:
            return match.group(0)
        slug = heading_slug(match.group('content')) or 'section'
        count = current['seen'].get(slug, 0)
        current['seen'][slug] = count + 1
        anchor = _section_anchor(current['doc'], slug if count == 0 else f'{slug}-{count}')
        level = match.group('level')
        return f'<h{level} id="{anchor}">{match.group("content")}</h{level}>'

    return token.sub(replace, body_html)


def _build_pdf(
    included_sections: list[str] = None,
    include_cover: bool = True,
    output_path: Path = None,
    included_pages: list[str] = None,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    doc_ids = _sorted_docs(included_sections, included_pages)
    if not doc_ids:
        raise RuntimeError('No documentation markdown files found for the given selection.')

    if output_path is None:
        output_path = OUTPUT_PDF_PATH

    # 1. Prepare and combine markdown
    print('Preparing combined markdown...')
    combined_md = _prepare_document(doc_ids, include_cover)
    COMBINED_MD_PATH.write_text(combined_md, encoding='utf-8')

    # 2. Convert markdown to HTML using mistune
    print('Converting markdown to HTML using mistune...')
    md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'table', 'url'])
    body_html = md(combined_md)
    body_html = _add_section_heading_ids(body_html)
    body_html = _rewrite_svg_img_tags_in_html(body_html, source_dir=DOCS_DIR)
    
    # Wrap in standard HTML template
    full_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Stop Sync OSM Atlas Documentation</title>
</head>
<body>
{body_html}
</body>
</html>
'''
    OUTPUT_HTML_PATH.write_text(full_html, encoding='utf-8')
    
    # 3. Print to PDF using WeasyPrint
    print('Printing to PDF using WeasyPrint...')
    html_doc = HTML(string=full_html, base_url=str(DOCS_DIR.absolute()))
    css_doc = CSS(filename=str(STYLE_PATH.absolute()))
    html_doc.write_pdf(target=str(output_path.absolute()), stylesheets=[css_doc])
    return output_path


if __name__ == '__main__':
    try:
        _build_pdf()
        print(f'PDF successfully generated at {OUTPUT_PDF_PATH}')
    except Exception as error:
        print(f'PDF generation failed: {error}', file=sys.stderr)
        sys.exit(1)
