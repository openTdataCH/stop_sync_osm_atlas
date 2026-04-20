from __future__ import annotations

import hashlib
import html
import re
import ssl
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import mistune
from weasyprint import HTML, CSS

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services.docs_stats import load_stats_for_docs, replace_stats_placeholders, convert_github_alerts_to_html, get_canonical_palette_html


DOCS_DIR = REPO_ROOT / 'documentation'
OUTPUT_DIR = DOCS_DIR / 'generated'
DIAGRAMS_DIR = OUTPUT_DIR / 'diagrams'
STYLE_PATH = DOCS_DIR / 'pdf_generator' / 'docs_print.css'
COMBINED_MD_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.md'
OUTPUT_HTML_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.html'
OUTPUT_PDF_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_documentation.pdf'
GITHUB_BLOB_BASE = 'https://github.com/openTdataCH/stop_sync_osm_atlas/blob/main/'
KROKI_MERMAID_ENDPOINT = 'https://kroki.io/mermaid/svg'
SVG_NS = 'http://www.w3.org/2000/svg'
XHTML_NS = 'http://www.w3.org/1999/xhtml'

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
    head = text.split('.', 1)[0]
    return head if head.isdigit() else None


def _sorted_docs(included_sections: list[str] = None) -> list[Path]:
    docs = sorted(
        [path for path in DOCS_DIR.glob('*.md') if path.is_file()],
        key=lambda path: path.name.lower(),
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
            top_key = _top_level_section_key(doc.name)
            if top_key and top_key in normalized_sections:
                filtered_docs.append(doc)
        return filtered_docs
    return docs


def _doc_anchor_map(doc_paths: list[Path]) -> dict[str, str]:
    return {path.name: f'doc-{_slugify(path.stem)}' for path in doc_paths}


def _rewrite_internal_doc_links(content: str, anchor_map: dict[str, str]) -> str:
    pattern = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)]+\.md(?:#[^)]+)?)\)')

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        href = match.group(2)
        if href.startswith(('http://', 'https://', '/')):
            return match.group(0)

        path_part = href.split('#', 1)[0]
        filename = Path(unquote(path_part)).name
        anchor = anchor_map.get(filename)
        if not anchor:
            return match.group(0)
        return f'[{label}](#{anchor})'

    return pattern.sub(replace, content)


def _rewrite_repo_links(content: str) -> str:
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

        base = href.split('#', 1)[0].split('?', 1)[0]
        normalized = base.lstrip('./')
        while normalized.startswith('../'):
            normalized = normalized[3:]
        suffix = Path(normalized).suffix.lower()
        if Path(normalized).name.lower() != 'dockerfile' and suffix not in code_like_exts:
            return match.group(0)

        return f'[{label}]({GITHUB_BLOB_BASE}{normalized.replace(" ", "%20")})'

    return pattern.sub(replace, content)


def _fetch_mermaid_svg(diagram_source: str) -> str:
    payload = diagram_source.encode('utf-8')
    request = Request(
        KROKI_MERMAID_ENDPOINT,
        data=payload,
        headers={
            'Content-Type': 'text/plain; charset=utf-8',
            'User-Agent': 'stop-sync-osm-atlas-docs/1.0',
        },
        method='POST',
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urlopen(request, timeout=45, context=ctx) as response:
        return response.read().decode('utf-8')


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

            text_elem = ET.Element(f'{{{SVG_NS}}}text', {
                'x': f'{x + (width / 2):.3f}',
                'y': f'{y + (height / 2):.3f}',
                'text-anchor': 'middle',
                'dominant-baseline': 'middle',
                'font-family': 'DejaVu Sans,Trebuchet MS,Verdana,Arial,sans-serif',
                'font-size': '15',
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
    decoded = unquote(asset_ref)

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
        if src.startswith(('http://', 'https://', 'data:', 'file:', '/')):
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


def _render_mermaid_to_local_svg(diagram_source: str) -> Path:
    normalized_source = diagram_source.strip() + '\n'
    if "%%{init:" not in normalized_source:
        normalized_source = (
            "%%{init: {'theme': 'neutral', 'flowchart': {'htmlLabels': false}}}%%\n"
            + normalized_source
        )

    digest = hashlib.sha256(normalized_source.encode('utf-8')).hexdigest()[:16]
    output_path = DIAGRAMS_DIR / f'mermaid-{digest}.svg'
    if output_path.exists():
        return output_path

    svg = _fetch_mermaid_svg(normalized_source)
    svg = _convert_foreign_objects_to_svg_text(svg)
    svg = _ensure_svg_text_visibility(svg)
    output_path.write_text(svg, encoding='utf-8')
    return output_path


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
            f'<div id="{anchor_map[doc_path.name]}" class="doc-anchor"></div>',
            '',
        ])

        content = doc_path.read_text(encoding='utf-8')
        
        mermaid_blocks = []
        def save_mermaid(match: re.Match[str]) -> str:
            mermaid_blocks.append(match.group(0))
            return f"<!--MERMAID_BLOCK_{len(mermaid_blocks)-1}-->"

        content = re.sub(r'```mermaid.*?```', save_mermaid, content, flags=re.DOTALL)
        
        content = replace_stats_placeholders(content, stats, html_escape=True)
        content = _rewrite_internal_doc_links(content, anchor_map)
        content = _rewrite_repo_links(content)
        content = convert_github_alerts_to_html(content)
        if '[[canonical_palette]]' in content:
            content = content.replace('[[canonical_palette]]', get_canonical_palette_html())
            
        def restore_mermaid(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            block = mermaid_blocks[idx]
            return replace_stats_placeholders(block, stats, html_escape=True, no_span=True)
            
        content = re.sub(r'<!--MERMAID_BLOCK_(\d+)-->', restore_mermaid, content)
        
        content = _rewrite_mermaid_blocks(content)
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