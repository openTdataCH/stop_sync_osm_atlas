"""The documentation portal and PDF render Markdown faithfully and link precisely."""
from html import unescape
import re

import pytest

_HREF = re.compile(r'<a\b[^>]*\bhref="([^"]+)"')
_ID = re.compile(r'\bid="([^"]+)"')


@pytest.fixture(scope='module')
def app():
    from backend.app import create_app

    app = create_app()
    app.config['TESTING'] = True
    return app


def _render(app, markdown, doc='documentation/2.8 Documentation Page Delivery.md'):
    from backend.blueprints.docs import _build_doc_slug_maps, _convert_markdown_to_html, _list_markdown_files

    with app.test_request_context():
        file_to_slug, _ = _build_doc_slug_maps(_list_markdown_files())
        return _convert_markdown_to_html(markdown, file_to_slug, doc)


def test_code_keeps_paths_links_placeholders_and_alerts_literal(app):
    html = _render(app, '\n'.join([
        '```text',
        'backend/app.py {{stat:summary.match_rate_percent}} [[canonical_palette]]',
        '[Statistics](2.3%20Global%20Stats.md)',
        '> [!NOTE]',
        '```',
        '',
        'Inline: `{{stat:summary.match_rate_percent}}` and `[[canonical_palette]]`.',
        '',
        'Write `[Statistics](2.3%20Global%20Stats.md)` or `![Alt text](images/route-model.svg)`.',
    ]))
    code_block = re.search(r'<pre><code[^>]*>(.*?)</code></pre>', html, re.DOTALL).group(1)
    assert 'backend/app.py {{stat:summary.match_rate_percent}} [[canonical_palette]]' in code_block
    assert '[Statistics](2.3%20Global%20Stats.md)' in code_block
    assert '&gt; [!NOTE]' in code_block
    assert '<code>{{stat:summary.match_rate_percent}}</code>' in html
    assert '<code>[[canonical_palette]]</code>' in html
    assert '<code>[Statistics](2.3%20Global%20Stats.md)</code>' in html
    assert '<code>![Alt text](images/route-model.svg)</code>' in html


def test_percent_statistics_keep_their_value_and_unit():
    from backend.services.docs_stats import format_stat_value

    assert format_stat_value(89.5, 'summary.match_rate_percent') == '89.5%'
    # A rate below 1 % is not mistaken for a ratio.
    assert format_stat_value(0.8, 'summary.match_rate_percent') == '0.8%'
    assert format_stat_value(55015, 'summary.atlas_platforms') == '55,015'


def test_code_paths_link_to_the_repository(app):
    html = _render(app, 'See `backend/app.py` and backend/services/repo_scanner.py.')
    assert 'blob/main/backend/app.py"' in html
    assert 'blob/main/backend/services/repo_scanner.py"' in html


def test_only_written_out_urls_become_links(app):
    html = _render(app, 'Run build.py, read SourceStop.name and see https://example.org/page.')
    assert 'http://build.py' not in html
    assert 'http://SourceStop.name' not in html
    assert 'href="https://example.org/page"' in html


def test_single_newlines_do_not_break_sentences(app):
    assert '<br' not in _render(app, 'The first half of a sentence\ncontinues on the next line.')


def test_engine_source_links_need_a_public_base(app, monkeypatch):
    markdown = '[profile](../engine/src/transport_matcher/core/profile.py)'
    monkeypatch.delenv('DOCS_ENGINE_BLOB_BASE', raising=False)
    assert '<a ' not in _render(app, markdown)

    monkeypatch.setenv('DOCS_ENGINE_BLOB_BASE', 'https://example.org/engine/blob/abc')
    assert 'href="https://example.org/engine/blob/abc/src/transport_matcher/core/profile.py"' in _render(app, markdown)


def test_every_portal_link_reaches_a_page_and_anchor(app):
    from backend.blueprints.docs import _build_doc_slug_maps, _list_markdown_files

    file_to_slug, _ = _build_doc_slug_maps(_list_markdown_files())
    pages = {}
    with app.test_client() as client:
        for slug in sorted(file_to_slug.values()):
            response = client.get(f'/docs/{slug}', headers={'X-Docs-Partial': '1'})
            assert response.status_code == 200, slug
            pages[slug] = response.get_json()['content_html']
    ids = {slug: set(_ID.findall(html)) for slug, html in pages.items()}

    problems = []
    for slug, html in pages.items():
        for href in map(unescape, _HREF.findall(html)):
            if href.startswith(('http://', 'https://', 'mailto:')):
                continue
            if href.startswith('#'):
                target, fragment = slug, href[1:]
            elif href.startswith('/docs/'):
                target, _, fragment = href[len('/docs/'):].partition('#')
                if target.startswith(('assets/', 'quality-artifacts/')):
                    continue
                if target not in pages:
                    problems.append(f'{slug}: {href} is not a documentation page')
                    continue
            elif href.startswith('/'):
                continue  # another page of the web app
            else:
                problems.append(f'{slug}: relative link {href} would not resolve')
                continue
            if fragment and fragment not in ids[target]:
                problems.append(f'{slug}: {href} points to a missing section')
    assert not problems, '\n'.join(problems)


def test_every_pdf_link_reaches_an_anchor(monkeypatch):
    import mistune
    from documentation.pdf_generator import build_docs_pdf as pdf

    # Mermaid output is irrelevant to links and is not pre-rendered in tests.
    monkeypatch.setattr(pdf, '_rewrite_mermaid_blocks', lambda content: content)
    combined = pdf._prepare_document(pdf._sorted_docs(), include_cover=False)
    renderer = mistune.create_markdown(escape=False, plugins=['strikethrough', 'table', 'url'])
    html = pdf._add_section_heading_ids(renderer(combined))
    ids = set(_ID.findall(html))

    problems = set()
    for href in map(unescape, _HREF.findall(html)):
        if href.startswith(('http://', 'https://', 'mailto:')):
            continue
        if not href.startswith('#'):
            problems.add(f'relative link {href} would not resolve in the PDF')
        elif href[1:] not in ids:
            problems.add(f'{href} points to a missing section')
    assert not problems, '\n'.join(sorted(problems))
