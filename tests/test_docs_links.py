from pathlib import Path
import re
from urllib.parse import unquote
import pytest


def _documentation_roots():
    from backend.version import engine_dir

    return Path(__file__).resolve().parents[1] / 'documentation', engine_dir() / 'documentation'


def _document_id(path):
    app_docs, engine_docs = _documentation_roots()
    if path.is_relative_to(engine_docs):
        return 'engine/documentation/' + str(path.relative_to(engine_docs))
    return 'documentation/' + str(path.relative_to(app_docs))


def test_documentation_links():
    """
    Scans app- and engine-owned Markdown and validates relative links.
    """
    docs_dirs = _documentation_roots()
    missing_dirs = [str(path) for path in docs_dirs if not path.exists()]
    if missing_dirs:
        pytest.fail(f"Documentation directories not found: {', '.join(missing_dirs)}")

    broken_links = []
    total_links = 0
    
    # Sort for consistent checking order
    md_files = sorted(
        (path for docs_dir in docs_dirs for path in docs_dir.glob("*.md")),
        key=lambda path: _document_id(path).lower(),
    )
    
    for md_file in md_files:
        with open(md_file, encoding='utf-8') as f:
            content = f.read()
        
        # Find all markdown links to .md files
        # Matches [text](link.md) or [text](subdir/link.md)
        # Does not match http/https links
        links = re.findall(r'\[[^\]]+\]\(([^)]+\.md[^)]*)\)', content)
        
        for link in links:
            if link.startswith(('https://', 'http://', 'mailto:', '#')):
                continue
            total_links += 1
            # Clean URL: decode URL encoding (e.g., %20 -> space) and remove anchors
            clean_link = unquote(link.split('#')[0])
            
            target = (md_file.parent / clean_link).resolve()
            # Markdown uses the portal's logical engine/ path in both nested
            # CI checkouts and the supported sibling/ENGINE_DIR layout.
            logical_engine = docs_dirs[0].parent / 'engine'
            if target.is_relative_to(logical_engine):
                target = docs_dirs[1].parent / target.relative_to(logical_engine)
            
            if not target.exists():
                broken_links.append({
                    'file': _document_id(md_file),
                    'link': link,
                    'target': str(target)
                })

    # Report results
    print(f"Total links checked: {total_links}")
    
    if broken_links:
        message = ["❌ BROKEN LINKS DETECTED:", "=" * 60]
        for item in broken_links:
            message.append(f"\nFile: {item['file']}")
            message.append(f"  Link: {item['link']}")
            message.append(f"  Target: {item['target']}")
        
        pytest.fail("\n".join(message))


def test_file_names_match_page_titles():
    """A page's file is named after its title without the owner's letter: `# E1 Input …` is `1. Input ….md`."""
    mismatched = []
    for path in (path for docs_dir in _documentation_roots() for path in docs_dir.glob('*.md')):
        if path.name == 'Changelog.md':
            continue
        title = next((line[2:].strip() for line in path.read_text(encoding='utf-8').splitlines() if line.startswith('# ')), '')
        expected = re.sub(r'^(\d+) ', r'\1. ', re.sub(r'^[EA](?=\d)', '', title)) + '.md'
        if path.name != expected:
            mismatched.append(f'{_document_id(path)}: expected {expected!r}')
    assert not mismatched, '\n'.join(mismatched)


def _page_header(soup):
    """Return the eyebrow (collection and number) and title of a docs page."""
    header = soup.select_one('#docs-page-header')
    assert header is not None
    eyebrow = header.select_one('.docs-page-eyebrow')
    return (
        eyebrow.get_text(' ', strip=True) if eyebrow else None,
        header.select_one('h1').get_text(' ', strip=True),
    )


def test_docs_portal_labels_engine_and_application_boundaries():
    from backend.app import create_app
    from backend.services.docs_sources import engine_version
    from backend.version import APP_VERSION
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        response = client.get('/docs/reference_matching')
        assert response.status_code == 200
        soup = BeautifulSoup(response.data.decode('utf-8'), 'html.parser')

        collection_labels = {
            node.get_text(' ', strip=True)
            for node in soup.select('#docsSidebar .docs-collection-label')
        }
        assert collection_labels == {'Matching engine', 'Review application'}
        # The project collections sit under one "For developers" heading.
        audience = soup.select('#docsSidebar .docs-audience-heading')
        assert [node.get_text(strip=True) for node in audience] == ['For users', 'For developers']

        # Each project's collections show the version of that project.
        versions = {
            node.find_parent(class_='docs-collection').select_one('.docs-collection-label').get_text(strip=True):
                node.get_text(strip=True)
            for node in soup.select('.docs-collection-version')
        }
        assert versions == {
            'Matching engine': f'v{engine_version()}',
            'Review application': f'v{APP_VERSION}',
        }

        navbar_version = soup.select_one('.navbar-version--brand')
        assert navbar_version is not None
        assert navbar_version.get_text(' ', strip=True) == f'Version {APP_VERSION}'

        overview_link = soup.find('a', href='/docs/user_guide')
        assert overview_link is not None
        assert overview_link.get_text(' ', strip=True) == '0 User guide'

        # Each collection carries its owner, which sets its colour.
        owners = {
            node.get('data-owner')
            for node in soup.select('.docs-collection')
        }
        assert owners == {'shared', 'engine', 'app'}
        assert soup.select_one('.docs-collection--engine')['data-owner'] == 'engine'
        assert soup.select_one('.docs-collection--app')['data-owner'] == 'app'

        # The heading leaves the article for the page header, which names
        # the collection, in its owner's colour, and the owner-scoped number.
        assert _page_header(soup) == ('Matching engine · E.2.1', 'Reference matching')
        assert soup.select_one('.docs-page-eyebrow')['data-owner'] == 'engine'
        assert soup.select_one('#docs-content-html h1') is None
        pdf = soup.select_one('#docs-page-header [data-pdf-scope="page"]')
        assert (pdf['data-page-slug'], pdf['data-page-section'], pdf['data-page-label']) == (
            'reference_matching', 'engine-2', 'E.2.1 Reference matching',
        )
        assert soup.select('#docs-page-header a') == []

        overview = BeautifulSoup(client.get('/docs').data.decode('utf-8'), 'html.parser')
        assert _page_header(overview) == ('User guide · 0', 'User guide')
        assert overview.select_one('.docs-page-eyebrow')['data-owner'] == 'shared'

        partial = client.get('/docs/database_bundle_import', headers={'X-Docs-Partial': '1'})
        assert partial.status_code == 200
        payload = partial.get_json()
        header = BeautifulSoup(payload['header_html'], 'html.parser')
        assert header.select_one('.docs-page-eyebrow').get_text(' ', strip=True) == 'Review application · A.1'
        assert header.select_one('h1').get_text(strip=True) == 'Database & bundle import'
        assert header.select_one('.docs-page-eyebrow')['data-owner'] == 'app'
        assert header.select_one('[data-pdf-scope="page"]')['data-page-label'] == 'A.1 Database & bundle import'
        assert '<h1' not in payload['content_html']


def test_docs_portal_uses_project_scoped_section_numbers():
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        response = client.get('/docs')
        assert response.status_code == 200
        soup = BeautifulSoup(response.data.decode('utf-8'), 'html.parser')

        for href, number, title in (
            ('/docs/input_integrations_acquisition', 'E.1', 'Input integrations & acquisition'),
            ('/docs/source_snapshot_caching', 'E.5.1', 'Source snapshot caching'),
            ('/docs/engine_tests', 'E.6', 'Engine tests'),
            ('/docs/database_bundle_import', 'A.1', 'Database & bundle import'),
            ('/docs/frontend_asset_management', 'A.3.4', 'Frontend asset management'),
            ('/docs/tests_code_quality', 'A.4', 'Tests & code quality'),
            ('/docs/backend_tests', 'A.4.1', 'Backend tests'),
            ('/docs/comparing_routes', '0.2', 'Comparing routes'),
            ('/docs/working_through_problems', '0.1', 'Working through problems'),
            ('/docs/glossary', '0.4', 'Glossary'),
        ):
            node = soup.find('a', href=href)
            assert node is not None, href
            assert node.select_one('.docs-nav-number').get_text(strip=True) == number
            assert node.select_one('.docs-nav-title').get_text(strip=True) == title
            assert node.get_text(' ', strip=True) == f'{number} {title}'

        contributing = soup.find('a', href='/docs/contributing')
        assert contributing is not None
        assert contributing.select_one('.docs-nav-number') is None
        assert contributing.get_text(' ', strip=True) == 'Contributing'

        web_tests = BeautifulSoup(client.get('/docs/tests_code_quality').data.decode('utf-8'), 'html.parser')
        assert _page_header(web_tests) == ('Review application · A.4', 'Tests & code quality')

        contributing_page = BeautifulSoup(client.get('/docs/contributing').data.decode('utf-8'), 'html.parser')
        assert _page_header(contributing_page) == ('Review application', 'Contributing')


def test_docs_sidebar_marks_the_page_being_read():
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        soup = BeautifulSoup(client.get('/docs/source_snapshot_caching').data.decode('utf-8'), 'html.parser')

    current = soup.select('#docsSidebar [aria-current="page"]')
    assert [link['href'] for link in current] == ['/docs/source_snapshot_caching']
    assert 'active' in current[0]['class']
    # Its section is marked as the current one, but only the page is highlighted.
    header = current[0].find_parent(class_='docs-section').select_one('.docs-section-header')
    assert 'is-current' in header['class']
    assert 'active' not in header['class']
    assert soup.select('.docs-section-header.is-current') == [header]


def test_app_and_engine_changelogs_have_distinct_canonical_routes():
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        app_response = client.get('/docs/changelog')
        assert app_response.status_code == 200
        app_soup = BeautifulSoup(app_response.data.decode('utf-8'), 'html.parser')
        assert _page_header(app_soup) == ('Review application', 'Review application changelog')
        assert app_soup.find('a', href='/docs/engine_changelog') is not None

        engine_response = client.get('/docs/engine_changelog')
        assert engine_response.status_code == 200
        engine_soup = BeautifulSoup(engine_response.data.decode('utf-8'), 'html.parser')
        assert _page_header(engine_soup) == ('Matching engine', 'Matching engine changelog')
        assert engine_soup.find('a', href='/docs/changelog') is not None


def test_engine_documentation_assets_are_served_from_engine_tree():
    from backend.app import create_app

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        page = client.get('/docs/matching_process')
        assert page.status_code == 200
        assert b'/docs/assets/engine/images/two-sided-stop-match-illustration.svg' in page.data

        asset = client.get('/docs/assets/engine/images/two-sided-stop-match-illustration.svg')
        assert asset.status_code == 200
        assert asset.mimetype == 'image/svg+xml'


def test_pdf_document_selection_keeps_engine_and_app_sections_distinct():
    from documentation.pdf_generator.build_docs_pdf import _prepare_document, _sorted_docs

    all_docs = _sorted_docs()
    assert all_docs[0] == 'documentation/0. User guide.md'
    assert 'engine/documentation/2. Matching process.md' in all_docs
    assert 'documentation/2. Web app.md' in all_docs
    assert all_docs.index('engine/documentation/2. Matching process.md') < all_docs.index('documentation/2. Web app.md')

    engine_only = _sorted_docs(['engine:2'])
    assert engine_only
    assert all(doc.startswith('engine/documentation/2') for doc in engine_only)
    assert {'engine/documentation/2. Matching process.md', 'engine/documentation/2.1 Reference matching.md'} <= set(engine_only)

    app_only = _sorted_docs(['app:2'])
    assert app_only
    assert all(doc.startswith('documentation/2') for doc in app_only)
    assert {'documentation/2. Web app.md', 'documentation/2.8 Documentation portal.md'} <= set(app_only)

    # A single page, alone or with sections, keeps the sidebar order.
    page = _sorted_docs(included_pages=['engine/documentation/2.1 Reference matching.md'])
    assert page == ['engine/documentation/2.1 Reference matching.md']
    mixed = _sorted_docs(['app:2'], ['engine/documentation/2.1 Reference matching.md'])
    assert mixed[0] == 'engine/documentation/2.1 Reference matching.md'
    assert mixed[1:] == app_only
    assert _sorted_docs(included_pages=['documentation/No such page.md']) == []

    # Unnumbered pages are selected by the keys the export dialog sends.
    changelogs = _sorted_docs(['app:extra-changelog', 'engine:extra-changelog'])
    assert changelogs == ['engine/documentation/Changelog.md', 'documentation/Changelog.md']
    combined = _prepare_document(changelogs, include_cover=False)
    assert 'id="doc-changelog"' in combined
    assert 'id="doc-engine_changelog"' in combined
    assert '](#doc-engine_changelog)' in combined


def test_engine_links_to_application_docs_on_github_point_at_the_page():
    """An engine page links to the application docs by their GitHub URL; the portal and PDF link the page itself."""
    from backend.services.docs_sources import rewrite_doc_links

    file_to_slug = {'documentation/0.4 Glossary.md': 'glossary'}
    text = (
        '[group](https://github.com/openTdataCH/stop_sync_osm_atlas/blob/main/documentation/'
        '0.4%20Glossary.md#duplicate-group) and [elsewhere](https://example.org/a.md)'
    )
    rewritten = rewrite_doc_links(
        text, file_to_slug, 'engine/documentation/4.1 Stop problems.md',
        lambda slug, fragment: f'#{slug}-{fragment}',
    )
    assert rewritten == '[group](#glossary-duplicate-group) and [elsewhere](https://example.org/a.md)'


def test_every_section_of_the_export_dialog_selects_pages():
    """The dialog sends each section's export key; the PDF must find its pages."""
    from backend.services.docs_sources import build_doc_collections, build_doc_slug_maps, list_markdown_files
    from documentation.pdf_generator.build_docs_pdf import _sorted_docs

    files = list_markdown_files()
    collections = build_doc_collections(files, build_doc_slug_maps(files)[0])
    sections = [section for collection in collections for section in collection['sections']]
    assert sections
    empty = [section['export_key'] for section in sections if not _sorted_docs([section['export_key']])]
    assert not empty


def test_auto_linking_of_repo_files():
    """Verify that Python files mentioned in docs are automatically linked to GitHub."""
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        # Check a page with plain-text code file mentions outside Mermaid.
        response = client.get('/docs/documentation_portal')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        soup = BeautifulSoup(html, 'html.parser')

        # 1. Check plain text/code links
        github_links = [a for a in soup.find_all('a', href=True) if 'github.com' in a['href']]
        assert len(github_links) > 0, "No GitHub links found in rendered HTML"

        docs_py_link = next((a for a in github_links if a['href'].endswith('/backend/blueprints/docs.py')), None)
        assert docs_py_link is not None, "docs.py was not automatically linked"

        repo_scanner_link = next((a for a in github_links if a['href'].endswith('/backend/services/repo_scanner.py')), None)
        assert repo_scanner_link is not None, "repo_scanner.py was not automatically linked"

        # 2. Mermaid nodes named after files must not receive Markdown links
        response = client.get('/docs/osm_input_and_acquisition')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        soup = BeautifulSoup(html, 'html.parser')

        mermaid_divs = soup.find_all('div', class_='mermaid')
        assert len(mermaid_divs) > 0, "No Mermaid diagrams found"
        
        for div in mermaid_divs:
            assert '<a ' not in div.decode_contents()
            assert '[get_atlas_gtfs.py](' not in div.get_text()

        # Exercise automatic Mermaid linking with a stable app-owned code file,
        # independently of the current source-acquisition diagram content.
        from backend.services.docs_render import auto_link_code_files
        with app.test_request_context():
            linked = auto_link_code_files('```mermaid\nflowchart LR\n    D[docs.py]\n```')
        assert 'click D' in linked and '/backend/blueprints/docs.py' in linked


@pytest.mark.parametrize('layout', ['sibling', 'nested'])
def test_engine_paths_resolve_wherever_the_engine_checkout_is(tmp_path, layout):
    """A written-out engine path links in both layouts; a bare name shared by three files links nowhere."""
    from backend.services.repo_scanner import RepoScanner

    app_root = tmp_path / 'app'
    engine = tmp_path / 'engine' if layout == 'sibling' else app_root / 'engine'
    for path in (app_root / 'backend/blueprints/routes.py', app_root / 'backend/pages/routes.py',
                 engine / 'src/osm_public_transport_matcher/routes.py'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('')

    scanner = RepoScanner(str(app_root), str(engine))
    assert scanner.resolve_path('src/osm_public_transport_matcher/routes.py') == \
        'engine/src/osm_public_transport_matcher/routes.py'
    assert scanner.resolve_path('backend/pages/routes.py') == 'backend/pages/routes.py'
    assert scanner.resolve_path('routes.py') is None
    # Without the engine's source, as in the web image, the engine path stays unlinked.
    assert RepoScanner(str(app_root), str(tmp_path / 'absent')).resolve_path(
        'src/osm_public_transport_matcher/routes.py') is None


def test_docs_link_to_the_code_quality_dashboard():
    """The sidebar of every page and the header of A4.3 lead to /quality."""
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        overview = BeautifulSoup(client.get('/docs').data.decode('utf-8'), 'html.parser')
        sidebar_link = overview.select_one('.docs-sidebar-footer a[href="/quality"]')
        assert sidebar_link is not None
        assert sidebar_link.get_text(' ', strip=True) == 'Code quality dashboard'
        assert overview.select_one('#docs-page-header a[href="/quality"]') is None

        quality_page = BeautifulSoup(client.get('/docs/code_quality').data.decode('utf-8'), 'html.parser')
        header_link = quality_page.select_one('#docs-page-header a.docs-page-action[href="/quality"]')
        assert header_link is not None
        assert header_link.get_text(' ', strip=True) == 'Open the dashboard'

        partial = client.get('/docs/code_quality', headers={'X-Docs-Partial': '1'}).get_json()
        assert 'href="/quality"' in partial['header_html']
