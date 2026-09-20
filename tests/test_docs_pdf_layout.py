from pathlib import Path
import xml.etree.ElementTree as ET

import mistune
from weasyprint import CSS, HTML
from weasyprint.formatting_structure import boxes

from documentation.pdf_generator import build_docs_pdf as docs_builder
from documentation.pdf_generator.build_single_markdown_pdf import _build_single_markdown_pdf


REPO_ROOT = Path(__file__).resolve().parents[1]
PRINT_CSS = REPO_ROOT / "documentation" / "pdf_generator" / "docs_print.css"


def test_long_table_identifiers_stay_inside_printable_page():
    html = """
    <table>
      <thead>
        <tr>
          <th>Execution</th>
          <th>Predicate</th>
          <th>Match types</th>
          <th>What it actually does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>6</td>
          <td><code>GroupProximityPredicate</code></td>
          <td><code>long_distance_group_proximity_uic_name</code></td>
          <td>Matches grouped candidates without widening the table.</td>
        </tr>
      </tbody>
    </table>
    """

    document = HTML(string=html).render(stylesheets=[CSS(filename=str(PRINT_CSS))])
    page_box = document.pages[0]._page_box
    printable_right = page_box.position_x + page_box.margin_left + page_box.width
    table_boxes = [
        box
        for box in page_box.descendants()
        if isinstance(box, boxes.TableBox)
    ]

    assert table_boxes
    assert all(
        table.position_x + table.width <= printable_right
        for table in table_boxes
    )


def test_local_markdown_images_remain_safe_file_urls(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = image_dir / "diagram.svg"
    image_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" />',
        encoding="utf-8",
    )

    markdown = docs_builder._rewrite_markdown_asset_paths(
        "![A local diagram](images/diagram.svg)",
        tmp_path,
    )
    rendered = mistune.create_markdown(escape=False)(markdown)

    assert '#harmful-link' not in rendered
    assert image_path.as_uri() in rendered
    assert 'alt="A local diagram"' in rendered


def test_svg_fallback_labels_wrap_inside_their_box():
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" width="220" height="60">
      <foreignObject x="10" y="6" width="200" height="48">
        <div xmlns="http://www.w3.org/1999/xhtml">
          Lock ATLAS representative in matched_source_ids
        </div>
      </foreignObject>
    </svg>
    """

    converted = docs_builder._convert_foreign_objects_to_svg_text(svg)
    root = ET.fromstring(converted)
    text = next(
        element
        for element in root.iter()
        if element.tag.rsplit('}', 1)[-1] == 'text'
    )
    tspans = [
        element
        for element in text
        if element.tag.rsplit('}', 1)[-1] == 'tspan'
    ]

    assert len(tspans) >= 2
    assert ''.join(tspan.text or '' for tspan in tspans).replace(' ', '') == (
        'LockATLASrepresentativeinmatched_source_ids'
    )


def test_missing_mermaid_asset_requires_local_prerender(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_builder, 'DIAGRAMS_DIR', tmp_path)

    try:
        docs_builder._render_mermaid_to_local_svg('flowchart LR\n  A --> B')
    except RuntimeError as error:
        assert 'npm run docs:render-mermaid' in str(error)
    else:
        raise AssertionError('A missing Mermaid asset should fail closed')


def test_single_markdown_pdf_builds(tmp_path, monkeypatch):
    markdown_path = tmp_path / "single.md"
    output_path = tmp_path / "single.pdf"
    markdown_path.write_text("# Single document\n\nRendered content.\n", encoding="utf-8")
    monkeypatch.setattr(docs_builder, 'load_stats_for_docs', lambda: {})

    result = _build_single_markdown_pdf(markdown_path, output_path)

    assert result == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
