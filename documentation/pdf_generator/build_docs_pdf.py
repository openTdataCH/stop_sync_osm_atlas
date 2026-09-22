from __future__ import annotations

import hashlib
import html
import json
import os
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

from backend.services.docs_stats import load_stats_for_docs, replace_stats_placeholders, convert_github_alerts_to_html, get_canonical_palette_html
from backend.services.quality_report import replace_quality_placeholder


DOCS_DIR = REPO_ROOT / 'documentation'
_configured_engine_dir = os.getenv('ENGINE_DIR', '').strip()
if _configured_engine_dir:
    ENGINE_ROOT = Path(_configured_engine_dir)
    if not ENGINE_ROOT.is_absolute():
        ENGINE_ROOT = (REPO_ROOT / ENGINE_ROOT).resolve()
elif (REPO_ROOT / 'engine' / 'pyproject.toml').is_file():
    ENGINE_ROOT = REPO_ROOT / 'engine'
else:
    ENGINE_ROOT = REPO_ROOT.parent / 'engine'
ENGINE_DOCS_DIR = ENGINE_ROOT / 'documentation'
DOC_SOURCE_DIRS = {'app': DOCS_DIR, 'engine': ENGINE_DOCS_DIR}
OUTPUT_DIR = DOCS_DIR / 'generated'
DIAGRAMS_DIR = OUTPUT_DIR / 'diagrams'
STYLE_PATH = DOCS_DIR / 'pdf_generator' / 'docs_print.css'
COMBINED_MD_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.md'
OUTPUT_HTML_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.html'
OUTPUT_PDF_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_documentation.pdf'
GITHUB_BLOB_BASE = 'https://github.com/openTdataCH/stop_sync_osm_atlas/blob/main/'
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


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r'\.md$', '', slug)
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


def _top_level_section_key(filename: str) -> str | None:
    stem = Path(filename).stem
    token = stem.split(' ', 1)[0]
    token = token.rstrip('.')
    if not token:
        return None
    head = token.split('.', 1)[0]
    return head if head.isdigit() else None


def _normalize_section_key(value: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip().rstrip('.')
    if not text:
        return None
    namespace = ''
    if ':' in text:
        prefix, text = text.split(':', 1)
        prefix = prefix.strip().lower()
        if prefix not in DOC_SOURCE_DIRS:
            return None
        namespace = f'{prefix}:'
    head = text.split('.', 1)[0]
    if head.isdigit():
        return f'{namespace}{head}'
    if namespace and re.fullmatch(r'[a-z0-9_-]+', text):
        return f'{namespace}{text}'
    return None


def _doc_source_key(path: Path) -> str:
    resolved = path.resolve()
    for source_key, source_dir in DOC_SOURCE_DIRS.items():
        if resolved.parent == source_dir.resolve():
            return source_key
    raise ValueError(f'Unknown documentation source: {path}')


def _doc_section_key(path: Path) -> str:
    source_key = _doc_source_key(path)
    top_key = _top_level_section_key(path.name)
    if top_key:
        return f'{source_key}:{top_key}'
    return f'{source_key}:extra-{_slugify(path.stem)}'


def _sorted_docs(included_sections: list[str] = None) -> list[Path]:
    app_docs = [path for path in DOCS_DIR.glob('*.md') if path.is_file()]
    engine_docs = [path for path in ENGINE_DOCS_DIR.glob('*.md') if path.is_file()]
    overview = [path for path in app_docs if _top_level_section_key(path.name) == '0']
    app_reference = [path for path in app_docs if path not in overview]
    docs = (
        sorted(overview, key=lambda path: path.name.lower())
        + sorted(engine_docs, key=lambda path: path.name.lower())
        + sorted(app_reference, key=lambda path: path.name.lower())
    )
    if included_sections is not None:
        normalized_sections = {
            key for key in (_normalize_section_key(section) for section in included_sections)
            if key is not None
        }
        if not normalized_sections:
            return []

        filtered_docs = []
        for doc in docs:
            section_key = _doc_section_key(doc)
            legacy_key = _top_level_section_key(doc.name)
            if section_key in normalized_sections or legacy_key in normalized_sections:
                filtered_docs.append(doc)
        return filtered_docs
    return docs


def _doc_anchor_map(doc_paths: list[Path]) -> dict[str, str]:
    return {
        str(path.resolve()): f'doc-{_doc_source_key(path)}-{_slugify(path.stem)}'
        for path in doc_paths
    }


def _rewrite_internal_doc_links(
    content: str,
    anchor_map: dict[str, str],
    current_doc: Path,
) -> str:
    pattern = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)]+\.md(?:#[^)]+)?)\)')

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        href = match.group(2)
        app_docs_prefix = (
            'https://github.com/openTdataCH/stop_sync_osm_atlas/'
            'blob/main/documentation/'
        )
        if href.startswith(app_docs_prefix):
            path_part = href[len(app_docs_prefix):].split('#', 1)[0]
            target = (DOCS_DIR / unquote(path_part)).resolve()
        elif href.startswith(('http://', 'https://', '/')):
            return match.group(0)
        else:
            path_part = href.split('#', 1)[0]
            target = (current_doc.parent / unquote(path_part)).resolve()
        logical_engine_root = REPO_ROOT / 'engine'
        if target.is_relative_to(logical_engine_root):
            target = (ENGINE_ROOT / target.relative_to(logical_engine_root)).resolve()
        anchor = anchor_map.get(str(target))
        if not anchor:
            return match.group(0)
        return f'[{label}](#{anchor})'

    return pattern.sub(replace, content)


def _rewrite_repo_links(content: str, current_doc: Path) -> str:
    pattern = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)]+)\)')
    code_like_exts = {
        '.py', '.sql', '.sh', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg',
        '.js', '.ts', '.tsx', '.jsx', '.css', '.html', '.txt', '.xml'
    }

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        href = match.group(2)
        if href.startswith(('http://', 'https://', '/', '#', 'mailto:')):
            return match.group(0)
        if href.lower().endswith('.md') or '.md#' in href.lower():
            return match.group(0)
        if href.startswith(('images/', 'diagrams/', 'documentation/')):
            return match.group(0)

        base = unquote(href.split('#', 1)[0].split('?', 1)[0])
        candidate = (current_doc.parent / base).resolve()
        try:
            normalized = candidate.relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            return match.group(0)
        suffix = candidate.suffix.lower()
        if not candidate.is_file():
            return match.group(0)
        if candidate.name.lower() != 'dockerfile' and suffix not in code_like_exts and suffix != '.md':
            return match.group(0)

        return f'[{label}]({GITHUB_BLOB_BASE}{normalized.replace(" ", "%20")})'

    return pattern.sub(replace, content)


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
    
    for line in lines:
        match = re.match(r'^(#+)\s+(.*)$', line)
        if match:
            hashes = match.group(1)
            title = match.group(2)
            
            if shift > 0:
                hashes += '#' * shift
            
            if not first_heading_processed:
                if not title.startswith(prefix):
                    title = f"{prefix} {title}"
                first_heading_processed = True
                
            processed_lines.append(f"{hashes} {title}")
        else:
            processed_lines.append(line)
            
    return '\n'.join(processed_lines)


def _prepare_document(doc_paths: list[Path], include_cover: bool = True) -> str:
    anchor_map = _doc_anchor_map(doc_paths)
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

    for doc_path in doc_paths:
        parts.extend([
            f'<div id="{anchor_map[str(doc_path.resolve())]}" class="doc-anchor"></div>',
            '',
        ])

        content = doc_path.read_text(encoding='utf-8')
        
        mermaid_blocks = []
        def save_mermaid(match: re.Match[str]) -> str:
            mermaid_blocks.append(match.group(0))
            return f"<!--MERMAID_BLOCK_{len(mermaid_blocks)-1}-->"

        content = re.sub(r'```mermaid.*?```', save_mermaid, content, flags=re.DOTALL)
        
        content = replace_stats_placeholders(content, stats, html_escape=True)
        # A PDF has no application origin. Preserve evidence paths without
        # turning root-relative portal URLs into misleading file:// links.
        content = replace_quality_placeholder(content, REPO_ROOT, artifact_prefix=None)
        content = _rewrite_internal_doc_links(content, anchor_map, doc_path)
        content = _rewrite_repo_links(content, doc_path)
        content = convert_github_alerts_to_html(content)
        if '[[canonical_palette]]' in content:
            content = content.replace('[[canonical_palette]]', get_canonical_palette_html())
            
        def restore_mermaid(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            block = mermaid_blocks[idx]
            return replace_stats_placeholders(block, stats, html_escape=True, no_span=True)
            
        content = re.sub(r'<!--MERMAID_BLOCK_(\d+)-->', restore_mermaid, content)
        
        content = _rewrite_mermaid_blocks(content)
        content = _rewrite_markdown_asset_paths(content, doc_path.parent)
        content = _process_markdown_headers(content, doc_path.name)
        parts.append(content.strip())
        parts.append('')

    return '\n'.join(parts)


def _protect_math(match: re.Match[str]) -> str:
    return match.group(0).replace('\\', '\\\\')


def _build_pdf(included_sections: list[str] = None, include_cover: bool = True, output_path: Path = None) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    doc_paths = _sorted_docs(included_sections)
    if not doc_paths:
        raise RuntimeError('No documentation markdown files found for the given selection.')

    if output_path is None:
        output_path = OUTPUT_PDF_PATH

    # 1. Prepare and combine markdown
    print('Preparing combined markdown...')
    combined_md = _prepare_document(doc_paths, include_cover)
    COMBINED_MD_PATH.write_text(combined_md, encoding='utf-8')

    # 2. Convert markdown to HTML using mistune
    print('Converting markdown to HTML using mistune...')
    # Protect math blocks from escaping
    combined_md = re.sub(r'\$\$.*?\$\$', _protect_math, combined_md, flags=re.DOTALL)
    combined_md = re.sub(r'(?<!\$)\$[^\s$](?:.*?[^\s$])?\$(?!\$)', _protect_math, combined_md)
    
    md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'table', 'url'])
    body_html = md(combined_md)
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
