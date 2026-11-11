"""The documentation portal and PDF render Markdown faithfully and link precisely."""
from html import unescape
from pathlib import Path
import re

import pytest

_HREF = re.compile(r'<a\b[^>]*\bhref="([^"]+)"')
_ID = re.compile(r'\bid="([^"]+)"')
# A documentation link written out in a template or script: '/docs/<address>#<section>'.
_APP_DOC_LINK = re.compile(r'["\']/docs/(\w+)(?:#([\w-]+))?["\']')


@pytest.fixture(scope='module')
def app():
    from backend.app import create_app

    app = create_app()
    app.config['TESTING'] = True
    return app


def _render(app, markdown, doc='documentation/2.8 Documentation portal.md'):
    from backend.services.docs_render import convert_markdown_to_html
    from backend.services.docs_sources import build_doc_slug_maps, list_markdown_files

    with app.test_request_context():
        file_to_slug, _ = build_doc_slug_maps(list_markdown_files())
        return convert_markdown_to_html(markdown, file_to_slug, doc)


def test_code_keeps_paths_links_placeholders_and_alerts_literal(app):
    html = _render(app, '\n'.join([
        '```text',
        'backend/app.py {{stat:summary.match_rate_percent}} [[canonical_palette]]',
        '[Statistics](2.3%20Global%20statistics.md)',
        '> [!NOTE]',
        '```',
        '',
        'Inline: `{{stat:summary.match_rate_percent}}` and `[[canonical_palette]]`.',
        '',
        'Write `[Statistics](2.3%20Global%20statistics.md)` or `![Alt text](images/route-model.svg)`.',
    ]))
    code_block = re.search(r'<pre><code[^>]*>(.*?)</code></pre>', html, re.DOTALL).group(1)
    assert 'backend/app.py {{stat:summary.match_rate_percent}} [[canonical_palette]]' in code_block
    assert '[Statistics](2.3%20Global%20statistics.md)' in code_block
    assert '&gt; [!NOTE]' in code_block
    assert '<code>{{stat:summary.match_rate_percent}}</code>' in html
    assert '<code>[[canonical_palette]]</code>' in html
    assert '<code>[Statistics](2.3%20Global%20statistics.md)</code>' in html
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


def test_a_list_of_card_items_becomes_cards(app):
    html = _render(app, '\n'.join([
        '- <i class="fas fa-map"></i> **Map** · [Find a stop](2.1%20Map%20data%20loading%20and%20rendering.md#zoom-levels) — Every stop, with `filters`.',
        '- <i class="fas fa-route"></i> **Routes** · [Compare lines](2.6%20Routes%20pages.md) — Lines and variants.',
    ]))
    assert '<ul>' not in html
    cards = re.findall(r'<a class="docs-card" href="([^"]+)"', html)
    assert cards == ['/docs/map_data_loading_and_rendering#zoom-levels', '/docs/routes_pages']
    assert '<span class="docs-card-tag">Map</span>' in html
    assert '<span class="docs-card-title">Find a stop</span>' in html
    assert '<span class="docs-card-text">Every stop, with <code>filters</code>.</span>' in html
    assert '<i class="fas fa-map"></i>' in html


def test_a_list_with_one_ordinary_item_stays_a_list(app):
    html = _render(app, '\n'.join([
        '- <i class="fas fa-map"></i> **Map** · [Find a stop](2.6%20Routes%20pages.md) — Every stop.',
        '- An ordinary item with a [link](2.6%20Routes%20pages.md).',
    ]))
    assert '<ul>' in html and 'docs-card' not in html


def test_single_newlines_do_not_break_sentences(app):
    assert '<br' not in _render(app, 'The first half of a sentence\ncontinues on the next line.')


def test_engine_source_links_point_at_the_pinned_commit(app):
    from backend.version import engine_blob_base

    markdown = '[profile](../engine/src/osm_public_transport_matcher/core/profile.py)'
    href = f'{engine_blob_base()}src/osm_public_transport_matcher/core/profile.py'
    assert href.startswith('https://github.com/openTdataCH/osm-public-transport-matcher/blob/')
    assert f'href="{href}"' in _render(app, markdown)


def test_svg_diagrams_are_inlined_so_their_links_work(app):
    html = _render(app, '![Overview](images/overview-big-picture.svg)', doc='documentation/0. User guide.md')
    assert '<span class="docs-diagram"><svg ' in html
    assert '<img' not in html
    assert 'href="https://github.com/openTdataCH/osm-public-transport-matcher"' in html

    # Other images, SVGs not drawn by the kit (they may carry stylesheets)
    # and SVGs outside an images/ directory stay images.
    intro, matching = 'documentation/0. User guide.md', 'engine/documentation/2. Matching process.md'
    for markdown, doc in (('![Map](images/review-app-map-screenshot.png)', intro),
                          ('![Pair](images/osm-pair-match-illustration.svg)', matching),
                          ('![Logo](images/../../static/osm.svg)', intro),
                          ('![Missing](images/no-such-diagram.svg)', intro)):
        html = _render(app, markdown, doc=doc)
        assert '<img' in html and '<svg' not in html, markdown


@pytest.fixture(scope='module')
def pages(app):
    """The rendered article of every documentation page, by address."""
    from backend.services.docs_sources import build_doc_slug_maps, list_markdown_files

    file_to_slug, _ = build_doc_slug_maps(list_markdown_files())
    pages = {}
    with app.test_client() as client:
        for slug in sorted(file_to_slug.values()):
            response = client.get(f'/docs/{slug}', headers={'X-Docs-Partial': '1'})
            assert response.status_code == 200, slug
            pages[slug] = response.get_json()['content_html']
    return pages


def test_every_portal_link_reaches_a_page_and_anchor(pages):
    ids = {slug: set(_ID.findall(html)) for slug, html in pages.items()}

    problems = []
    for slug, html in pages.items():
        # Inlined diagrams share the page's ID namespace.
        all_ids = _ID.findall(html)
        problems += [f'{slug}: duplicate id {value}' for value in sorted(set(all_ids)) if all_ids.count(value) > 1]
        for href in map(unescape, _HREF.findall(html)):
            if href.startswith(('http://', 'https://', 'mailto:')):
                continue
            if href.startswith('#'):
                target, fragment = slug, href[1:]
            elif href.startswith('/docs/'):
                target, _, fragment = href[len('/docs/'):].partition('#')
                if target.startswith('assets/'):
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


def test_every_web_app_link_reaches_a_page_and_section(pages):
    """The info links of the filters, popups and Problems page open an existing section.

    Section anchors come from heading text, and an unknown one opens the page at
    the top without an error, so renaming a heading in either repository would
    break these links silently.
    """
    root = Path(__file__).resolve().parents[1]
    sources = sorted([*root.glob('templates/**/*.html'), *root.glob('static/js/**/*.js')])
    links, problems = [], []
    for path in sources:
        for slug, section in _APP_DOC_LINK.findall(path.read_text(encoding='utf-8')):
            link = f'/docs/{slug}' + (f'#{section}' if section else '')
            links.append(link)
            if slug not in pages:
                problems.append(f'{path.relative_to(root)}: {link} is not a documentation page')
            elif section and section not in _ID.findall(pages[slug]):
                problems.append(f'{path.relative_to(root)}: {link} points to a missing section')
    assert '/docs/stop_problems#distance-problems' in links  # the scan finds the links
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


def test_web_app_links_follow_the_serving_site_and_stay_text_in_the_pdf(app):
    from documentation.pdf_generator import build_docs_pdf as pdf

    html = _render(app, 'Open the [code quality dashboard](/quality).')
    assert 'href="/quality"' in html
    assert pdf._unlink_site_pages('Open the [code quality dashboard](/quality).') == 'Open the code quality dashboard.'
