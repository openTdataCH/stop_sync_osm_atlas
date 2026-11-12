import io
from pathlib import Path
import tarfile
import xml.etree.ElementTree as ET

import mistune
import pytest
from weasyprint import CSS, HTML
from weasyprint.formatting_structure import boxes
from weasyprint.urls import URLFetcher, URLFetchingError

from backend.services import docs_diagrams
from documentation.pdf_generator import build_docs_pdf as docs_builder


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
          <td><code>GroupDistancePredicate</code></td>
          <td><code>uic_name_group_long_distance</code></td>
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


DIAGRAM = 'flowchart LR\n  A --> B'
SHA = 'a' * 40
SET = f'diagrams-{SHA}.tar.gz'


def _archive(files):
    body = io.BytesIO()
    with tarfile.open(fileobj=body, mode='w:gz') as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return body.getvalue()


@pytest.fixture
def ci_diagrams(tmp_path, monkeypatch):
    """A checkout at SHA with no rendered diagrams. ``published`` is what CI uploaded, ``asked`` every download."""
    monkeypatch.setattr(docs_builder, 'DIAGRAMS_DIR', tmp_path)
    monkeypatch.setenv('APP_REVISION', SHA)
    published, asked = {}, []

    def download(name, max_bytes):
        asked.append(name)
        return published.get(name)

    monkeypatch.setattr(docs_diagrams.ci_release, 'download', download)
    return published, asked


def test_a_missing_diagram_comes_from_what_ci_rendered_for_this_commit_once(ci_diagrams):
    published, asked = ci_diagrams
    svg = docs_builder._mermaid_asset_path(DIAGRAM)
    other = docs_builder._mermaid_asset_path('flowchart LR\n  C --> D')
    published[SET] = _archive({svg.name: b'<svg/>'})

    assert docs_builder._render_mermaid_to_local_svg(DIAGRAM) == svg
    assert svg.read_bytes() == b'<svg/>'
    # The set of a commit never changes: a diagram it lacks is not asked for again.
    assert docs_builder._render_mermaid_to_local_svg('flowchart LR\n  C --> D') is None
    assert not other.exists() and asked == [SET]


def test_a_diagram_nobody_rendered_becomes_a_note_and_github_is_asked_again_later(ci_diagrams, monkeypatch):
    published, asked = ci_diagrams
    html = docs_builder._rewrite_mermaid_blocks(f'```mermaid\n{DIAGRAM}\n```')
    assert docs_builder.MISSING_DIAGRAM_CLASS in html and 'online documentation' in html and '<img' not in html
    docs_builder._rewrite_mermaid_blocks(f'```mermaid\n{DIAGRAM}\n```')
    assert asked == [SET]

    # CI has finished in the meantime.
    published[SET] = _archive({docs_builder._mermaid_asset_path(DIAGRAM).name: b'<svg/>'})
    later = docs_diagrams.time.time() + docs_diagrams.RETRY_SECONDS + 1
    monkeypatch.setattr(docs_diagrams.time, 'time', lambda: later)
    assert '<img' in docs_builder._rewrite_mermaid_blocks(f'```mermaid\n{DIAGRAM}\n```')
    assert asked == [SET, SET]


def test_only_rendered_diagrams_are_taken_from_the_archive(tmp_path, ci_diagrams):
    published, _ = ci_diagrams
    svg = docs_builder._mermaid_asset_path(DIAGRAM)
    published[SET] = _archive({'../escape.svg': b'x', f'sub/{svg.name}': b'x', 'notes.txt': b'x', svg.name: b'<svg/>'})
    assert docs_diagrams.fetch(tmp_path)
    assert not (tmp_path.parent / 'escape.svg').exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == [f'.ci-{SHA}', svg.name]


def test_without_a_known_commit_nothing_is_downloaded(ci_diagrams, monkeypatch):
    _, asked = ci_diagrams
    monkeypatch.setattr(docs_diagrams, 'app_revision', lambda: None)
    assert docs_builder._render_mermaid_to_local_svg(DIAGRAM) is None and asked == []


def test_one_page_pdf_builds(tmp_path, monkeypatch):
    for name in ('OUTPUT_DIR', 'DIAGRAMS_DIR'):
        monkeypatch.setattr(docs_builder, name, tmp_path)
    monkeypatch.setattr(docs_builder, 'COMBINED_MD_PATH', tmp_path / "bundle.md")
    monkeypatch.setattr(docs_builder, 'OUTPUT_HTML_PATH', tmp_path / "bundle.html")
    monkeypatch.setattr(docs_builder, 'load_stats_for_docs', lambda: {})
    # Mermaid is pre-rendered by the image build, not in tests.
    monkeypatch.setattr(docs_builder, '_rewrite_mermaid_blocks', lambda content: content)
    output_path = tmp_path / "page.pdf"

    result = docs_builder._build_pdf(
        included_pages=['documentation/2.8 Documentation portal.md'],
        include_cover=False,
        output_path=output_path,
    )

    assert result == output_path
    assert output_path.read_bytes().startswith(b'%PDF')


def test_stylesheet_parameter_respects_the_document_url_fetcher(tmp_path):
    """CVE-2026-55073: stylesheet arguments must not bypass resource policy."""
    stylesheet = tmp_path / 'blocked.css'
    stylesheet.write_text('@page { size: 1234px 5678px }')
    requested = []

    class BlockedResources(URLFetcher):
        def fetch(self, url, headers=None):
            requested.append(url)
            raise ValueError('Resource blocked by the document policy')

    with pytest.raises(URLFetchingError, match='Resource blocked by the document policy'):
        HTML(string='<p>Safe content</p>', url_fetcher=BlockedResources()).render(
            stylesheets=[stylesheet.as_uri()])

    assert requested == [stylesheet.as_uri()]
