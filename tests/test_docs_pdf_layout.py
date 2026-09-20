from pathlib import Path

from weasyprint import CSS, HTML
from weasyprint.formatting_structure import boxes


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
