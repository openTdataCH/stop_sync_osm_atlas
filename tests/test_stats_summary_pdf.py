import sys
import types

import flask

from backend.services import stats_export


def test_generate_stats_summary_pdf_prefers_embedded_problem_stats(app, monkeypatch, tmp_path):
    captured = {}

    def fake_render_template(template_name, **kwargs):
        captured['template_name'] = template_name
        captured['probs'] = kwargs['probs']
        captured['problem_breakdown'] = kwargs['problem_breakdown']
        return '<html>summary</html>'

    class FakeHTML:
        def __init__(self, string, base_url):
            captured['html_string'] = string
            captured['base_url'] = base_url

        def write_pdf(self, target_path):
            with open(target_path, 'wb') as handle:
                handle.write(b'%PDF-1.4 test\n')

    stats = {
        'problems': {
            'total_stops': 10,
            'clean_entries': 7,
            'stops_with_problems': 3,
            'multiple_problems': 1,
            'by_priority': {1: {'distance': 1}, 2: {'attributes': 2}},
        }
    }

    monkeypatch.setattr(flask, 'render_template', fake_render_template)
    monkeypatch.setattr(
        stats_export,
        'compute_db_stats',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('compute_db_stats should not run when stats already contain problems')),
    )
    monkeypatch.setitem(sys.modules, 'weasyprint', types.SimpleNamespace(HTML=FakeHTML))

    output_path = tmp_path / 'stats_summary.pdf'

    with app.app_context():
        returned_path = stats_export.generate_stats_summary_pdf(stats, output_path=str(output_path))

    assert returned_path == str(output_path)
    assert output_path.exists()
    assert captured['template_name'] == 'reports/stats_summary.html'
    assert captured['probs'] == stats['problems']
    assert captured['problem_breakdown'] == stats['problems']['by_priority']