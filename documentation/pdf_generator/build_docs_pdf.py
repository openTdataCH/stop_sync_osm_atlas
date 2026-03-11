from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / 'documentation'
OUTPUT_DIR = DOCS_DIR / 'generated'
DIAGRAMS_DIR = OUTPUT_DIR / 'diagrams'
STYLE_PATH = DOCS_DIR / 'pdf_generator' / 'docs_print.css'
COMBINED_MD_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.md'
OUTPUT_HTML_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_docs_bundle.html'
OUTPUT_PDF_PATH = OUTPUT_DIR / 'stop_sync_osm_atlas_documentation_bw.pdf'
GITHUB_BLOB_BASE = 'https://github.com/openTdataCH/stop_sync_osm_atlas/blob/main/'
KROKI_MERMAID_ENDPOINT = 'https://kroki.io/mermaid/svg'
SVG_NS = 'http://www.w3.org/2000/svg'
XHTML_NS = 'http://www.w3.org/1999/xhtml'

CHROME_CANDIDATES = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    'google-chrome',
    'google-chrome-stable',
    'chromium-browser',
    'chromium',
]

ET.register_namespace('', SVG_NS)


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r'\.md$', '', slug)
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


def _sorted_docs() -> list[Path]:
    return sorted(
        [path for path in DOCS_DIR.glob('*.md') if path.is_file()],
        key=lambda path: path.name.lower(),
    )


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


def _load_stats_for_docs() -> dict | None:
    stats_path = REPO_ROOT / 'data' / 'stats.json'
    if not stats_path.exists():
        return None
    try:
        return json.loads(stats_path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _get_nested_stat_value(stats: dict | None, key_path: str):
    if not stats:
        return None
    value = stats
    for key in key_path.split('.'):
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def _format_stat_value(value) -> str:
    if value is None:
        return '---'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, float):
        if 0 < value < 1:
            return f'{value:.1%}'
        return f'{value:,.1f}'
    if isinstance(value, int):
        return f'{value:,}'
    return str(value)


def _replace_stats_placeholders(content: str, stats: dict | None) -> str:
    pattern = re.compile(r'\{\{stat:([a-zA-Z0-9_.]+)\}\}')

    def replace(match: re.Match[str]) -> str:
        key_path = match.group(1)
        value = _get_nested_stat_value(stats, key_path)
        formatted = _format_stat_value(value)
        css_class = 'dynamic-stat'
        if value is None:
            css_class += ' stat-unavailable'
        return (
            f'<span class="{css_class}" data-stat-key="{escape(key_path)}" '
            f'title="Auto-updated from pipeline stats">{escape(formatted)}</span>'
        )

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
    with urlopen(request, timeout=45) as response:
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

            width = float(child.attrib.get('width', '0') or 0)
            height = float(child.attrib.get('height', '0') or 0)
            lines = _extract_foreign_object_lines(child)
            if not lines:
                parent.remove(child)
                continue

            text_elem = ET.Element(f'{{{SVG_NS}}}text', {
                'x': f'{width / 2:.3f}',
                'y': f'{height / 2:.3f}',
                'text-anchor': 'middle',
                'dominant-baseline': 'middle',
                'font-family': 'Trebuchet MS,Verdana,Arial,sans-serif',
                'font-size': '15',
            })

            line_count = len(lines)
            if line_count == 1:
                text_elem.text = lines[0]
            else:
                for line_index, line in enumerate(lines):
                    tspan = ET.SubElement(text_elem, f'{{{SVG_NS}}}tspan', {
                        'x': f'{width / 2:.3f}',
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


def _prepare_document(doc_paths: list[Path]) -> str:
    anchor_map = _doc_anchor_map(doc_paths)
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    stats = _load_stats_for_docs()

    parts = [
        '---',
        'title: Stop Sync OSM Atlas Documentation',
        'subtitle: Black-and-White Reference Edition',
        f'date: {generated_at}',
        'lang: en',
        '---',
        '',
        '<div class="title-page">',
        '<div class="title-page__eyebrow">Stop Sync OSM Atlas</div>',
        '<div class="title-page__title">Documentation Bundle</div>',
        '<div class="title-page__deck">A print-oriented export of the repository documentation, styled for grayscale readability and long-form reference use.</div>',
        '</div>',
        '',
        '<div class="page-break"></div>',
        '',
    ]

    for doc_path in doc_paths:
        parts.extend([
            f'<div id="{anchor_map[doc_path.name]}" class="doc-anchor"></div>',
            '',
        ])

        content = doc_path.read_text(encoding='utf-8')
        content = _replace_stats_placeholders(content, stats)
        content = _rewrite_internal_doc_links(content, anchor_map)
        content = _rewrite_repo_links(content)
        content = _rewrite_mermaid_blocks(content)
        content = _process_markdown_headers(content, doc_path.name)
        parts.append(content.strip())
        parts.append('')

    return '\n'.join(parts)


def _find_chrome() -> str | None:
    import shutil
    for candidate in CHROME_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
        
        # Check absolute path if it's a Mac app bundle
        candidate_path = Path(candidate)
        if candidate_path.is_absolute() and candidate_path.is_file():
            return candidate
            
    return None


def _build_pdf() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    doc_paths = _sorted_docs()
    if not doc_paths:
        raise RuntimeError('No documentation markdown files found.')

    # 1. Prepare and combine markdown
    COMBINED_MD_PATH.write_text(_prepare_document(doc_paths), encoding='utf-8')

    # 2. Build standalone HTML using Pandoc
    pandoc_command = [
        'pandoc',
        str(COMBINED_MD_PATH),
        '--from=gfm+pipe_tables+raw_html',
        '--to=html5',
        '--standalone',
        f'--css={STYLE_PATH.absolute()}',
        '--resource-path',
        f'{DOCS_DIR}:{REPO_ROOT}',
        '-o',
        str(OUTPUT_HTML_PATH),
    ]
    
    # Enable embed-resources so images are embedded (helps Chrome)
    pandoc_command.append('--embed-resources')
    
    print('Generating intermediate HTML with pandoc...')
    subprocess.run(pandoc_command, check=True, cwd=REPO_ROOT)
    
    # 3. Print to PDF using Headless Chrome
    chrome_path = _find_chrome()
    if not chrome_path:
        raise RuntimeError("Could not find Google Chrome or Chromium executable. Cannot generate PDF.")
        
    print(f'Printing to PDF using {chrome_path}...')
    
    # Make sure we use an absolute URI for Chrome
    html_uri = OUTPUT_HTML_PATH.absolute().as_uri()
    
    chrome_command = [
        chrome_path,
        '--headless',
        '--disable-gpu',
        '--no-pdf-header-footer',
        '--print-to-pdf-no-header',
        f'--print-to-pdf={OUTPUT_PDF_PATH.absolute()}',
        html_uri,
    ]
    
    subprocess.run(chrome_command, check=True)


if __name__ == '__main__':
    try:
        _build_pdf()
        print(f'PDF successfully generated at {OUTPUT_PDF_PATH}')
    except subprocess.CalledProcessError as error:
        print(f'PDF generation failed with exit code {error.returncode}', file=sys.stderr)
        sys.exit(error.returncode)
    except Exception as error:
        print(f'PDF generation failed: {error}', file=sys.stderr)
        sys.exit(1)