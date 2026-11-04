from pathlib import Path
import re
from urllib.parse import unquote
import pytest


def _documentation_roots():
    from backend.blueprints.docs import _engine_root

    return Path(__file__).resolve().parents[1] / 'documentation', Path(_engine_root()) / 'documentation'


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


def test_hard_coded_app_doc_links_use_canonical_slugs():
    """Catch template/JavaScript links that bypass Markdown link rewriting."""
    repo_root = Path(__file__).parent.parent
    docs_files = sorted(
        [path for root in _documentation_roots() for path in root.glob('*.md')],
        key=lambda path: _document_id(path).lower(),
    )

    slugs = set()
    for path in docs_files:
        base = re.sub(r'^\d+(?:\.\d+)*\.?\s*', '', path.stem).strip().lower()
        base_slug = re.sub(r'[^a-z0-9]+', '_', base).strip('_') or 'doc'
        slug = base_slug
        counter = 2
        while slug in slugs:
            slug = f"{base_slug}_{counter}"
            counter += 1
        slugs.add(slug)

    source_files = list((repo_root / "templates").rglob("*.html"))
    source_files.extend((repo_root / "static" / "js").rglob("*.js"))
    quoted_path = re.compile(r'''["'](/docs/(?!assets/|data/)[^"']+)["']''')
    broken = []

    for source_file in source_files:
        content = source_file.read_text(encoding="utf-8")
        for match in quoted_path.finditer(content):
            path = unquote(match.group(1).split('?', 1)[0].split('#', 1)[0]).rstrip('/')
            slug = path.removeprefix('/docs/')
            if slug and slug not in slugs:
                broken.append(f"{source_file.relative_to(repo_root)}: {match.group(1)}")

    assert not broken, "Hard-coded documentation links must use canonical slugs:\n" + "\n".join(broken)


def test_documentation_links_in_rendered_html():
    """
    Test that links rendered in the Flask web application work correctly.
    
    This catches issues where:
    - Markdown links (.md) aren't properly rewritten to Flask routes
    - Internal links result in 404 errors
    """
    try:
        import sys
        from pathlib import Path
        
        # Add repo root to path to import Flask app
        repo_root = Path(__file__).parent.parent
        sys.path.insert(0, str(repo_root))
        
        from backend.app import create_app
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse
    except ImportError as e:
        pytest.skip(f"Flask app or dependencies not available: {e}")
    
    app = create_app()
    app.config['TESTING'] = True
    
    with app.test_client() as client:
        # Get the intro page to find all doc links
        response = client.get('/docs')
        if response.status_code != 200:
            pytest.skip("Documentation route not available")
        
        html = response.data.decode('utf-8')
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all internal links in the rendered content
        broken_links = []
        tested_links = set()
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            parsed = urlparse(href)
            
            # Only test internal /docs/ links
            if not parsed.path.startswith('/docs'):
                continue
            
            # Skip duplicates
            if href in tested_links:
                continue
            tested_links.add(href)
            
            # Test the link
            link_response = client.get(parsed.path)
            if link_response.status_code != 200:
                broken_links.append({
                    'link': href,
                    'status': link_response.status_code,
                    'text': link.get_text(strip=True)[:50]
                })
        
        print(f"Tested {len(tested_links)} internal documentation links")
        
        if broken_links:
            message = ["❌ BROKEN LINKS IN RENDERED HTML:", "=" * 60]
            for item in broken_links:
                message.append(f"\n  Link: {item['link']}")
                message.append(f"  Text: {item['text']}")
                message.append(f"  Status: {item['status']}")
            pytest.fail("\n".join(message))


def test_docs_canonical_slug_urls():
    """Ensure docs use canonical slug URLs."""
    try:
        import sys
        from pathlib import Path

        repo_root = Path(__file__).parent.parent
        sys.path.insert(0, str(repo_root))

        from backend.app import create_app
        from bs4 import BeautifulSoup
    except ImportError as e:
        pytest.skip(f"Flask app or dependencies not available: {e}")

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        # Canonical slug route must resolve.
        canonical = client.get('/docs/exact_matching')
        assert canonical.status_code == 200

        # Sidebar and docs navigation links should be slug-based.
        root = client.get('/docs')
        assert root.status_code == 200
        soup = BeautifulSoup(root.data.decode('utf-8'), 'html.parser')

        docs_hrefs = {
            a['href']
            for a in soup.find_all('a', href=True)
            if a['href'].startswith('/docs/') and '/docs/assets/' not in a['href'] and '/docs/data/' not in a['href']
        }

        assert '/docs/exact_matching' in docs_hrefs


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
    from backend.blueprints.docs import _engine_version
    from backend.version import APP_VERSION
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        response = client.get('/docs/exact_matching')
        assert response.status_code == 200
        soup = BeautifulSoup(response.data.decode('utf-8'), 'html.parser')

        collection_labels = {
            node.get_text(' ', strip=True)
            for node in soup.select('#docsSidebar .docs-collection-label')
        }
        assert 'Engine input integrations' in collection_labels
        assert 'Matching engine core' in collection_labels
        assert 'Review application & deployment' in collection_labels
        assert 'Project overview' not in collection_labels

        # Each project's collections show the version of that project.
        versions = {
            node.find_parent(class_='docs-collection').select_one('.docs-collection-label').get_text(strip=True):
                node.get_text(strip=True)
            for node in soup.select('.docs-collection-version')
        }
        assert versions == {
            'Engine input integrations': f'v{_engine_version()}',
            'Matching engine core': f'v{_engine_version()}',
            'Review application & deployment': f'v{APP_VERSION}',
        }

        navbar_version = soup.select_one('.navbar-version--brand')
        assert navbar_version is not None
        assert navbar_version.get_text(' ', strip=True) == f'Version {APP_VERSION}'

        overview_link = soup.find('a', href='/docs/intro')
        assert overview_link is not None
        assert overview_link.get_text(' ', strip=True) == '0 Project overview'

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
        assert _page_header(soup) == ('Matching engine core · E.2.1', 'Exact matching')
        assert soup.select_one('.docs-page-eyebrow')['data-owner'] == 'engine'
        assert soup.select_one('#docs-content-html h1') is None
        pdf = soup.select_one('#docs-page-header [data-pdf-scope="page"]')
        assert (pdf['data-page-slug'], pdf['data-page-section'], pdf['data-page-label']) == (
            'exact_matching', 'engine-2', 'E.2.1 Exact matching',
        )
        assert soup.select('#docs-page-header a') == []

        overview = BeautifulSoup(client.get('/docs').data.decode('utf-8'), 'html.parser')
        assert _page_header(overview) == ('Project overview · 0', 'Project overview')
        assert overview.select_one('.docs-page-eyebrow')['data-owner'] == 'shared'

        partial = client.get('/docs/database', headers={'X-Docs-Partial': '1'})
        assert partial.status_code == 200
        payload = partial.get_json()
        header = BeautifulSoup(payload['header_html'], 'html.parser')
        assert header.select_one('.docs-page-eyebrow').get_text(' ', strip=True) == 'Review application & deployment · A.1'
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
            ('/docs/download_and_process_data', 'E.1', 'Input integrations & acquisition'),
            ('/docs/source_snapshot_caching', 'E.5.1', 'Source snapshot caching'),
            ('/docs/pipeline_tests', 'E.6', 'Engine tests'),
            ('/docs/database', 'A.1', 'Database & bundle import'),
            ('/docs/frontend_asset_management', 'A.3.4', 'Frontend asset management'),
            ('/docs/test', 'A.4', 'Tests & code quality'),
            ('/docs/backend_tests', 'A.4.1', 'Backend tests'),
            ('/docs/glossary', '0.1', 'Glossary'),
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

        web_tests = BeautifulSoup(client.get('/docs/test').data.decode('utf-8'), 'html.parser')
        assert _page_header(web_tests) == ('Review application & deployment · A.4', 'Tests & code quality')

        contributing_page = BeautifulSoup(client.get('/docs/contributing').data.decode('utf-8'), 'html.parser')
        assert _page_header(contributing_page) == ('Review application & deployment', 'Contributing')


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
        assert _page_header(app_soup) == ('Review application & deployment', 'Review application changelog')
        assert app_soup.find('a', href='/docs/engine_changelog') is not None

        engine_response = client.get('/docs/engine_changelog')
        assert engine_response.status_code == 200
        engine_soup = BeautifulSoup(engine_response.data.decode('utf-8'), 'html.parser')
        assert _page_header(engine_soup) == ('Matching engine core', 'Matching engine changelog')
        assert engine_soup.find('a', href='/docs/changelog') is not None


def test_engine_documentation_assets_are_served_from_engine_tree():
    from backend.app import create_app

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        page = client.get('/docs/matching_process')
        assert page.status_code == 200
        assert b'/docs/assets/engine/images/osm-trio-match-illustration.svg' in page.data

        asset = client.get('/docs/assets/engine/images/osm-trio-match-illustration.svg')
        assert asset.status_code == 200
        assert asset.mimetype == 'image/svg+xml'


def test_pdf_document_selection_keeps_engine_and_app_sections_distinct():
    from documentation.pdf_generator.build_docs_pdf import _prepare_document, _sorted_docs

    all_docs = _sorted_docs()
    relative = [_document_id(path) for path in all_docs]
    assert relative[0] == 'documentation/0. Intro.md'
    assert 'engine/documentation/2. Matching process.md' in relative
    assert 'documentation/2. Web app.md' in relative
    assert relative.index('engine/documentation/2. Matching process.md') < relative.index('documentation/2. Web app.md')

    engine_only = _sorted_docs(['engine:2'])
    assert engine_only
    assert all(path.parent == _documentation_roots()[1] for path in engine_only)
    assert {path.name for path in engine_only} >= {'2. Matching process.md', '2.1 Exact matching.md'}

    app_only = _sorted_docs(['app:2'])
    assert app_only
    assert all(path.parent == _documentation_roots()[0] for path in app_only)
    assert {path.name for path in app_only} >= {'2. Web app.md', '2.8 Documentation Page Delivery.md'}

    # A single page, alone or with sections, keeps the sidebar order.
    page = _sorted_docs(included_pages=['engine/documentation/2.1 Exact matching.md'])
    assert [_document_id(path) for path in page] == ['engine/documentation/2.1 Exact matching.md']
    mixed = _sorted_docs(['app:2'], ['engine/documentation/2.1 Exact matching.md'])
    assert _document_id(mixed[0]) == 'engine/documentation/2.1 Exact matching.md'
    assert mixed[1:] == app_only
    assert _sorted_docs(included_pages=['documentation/No such page.md']) == []

    changelogs = _sorted_docs(['app:extra-changelog', 'engine:extra-changelog'])
    assert len(changelogs) == 2
    combined = _prepare_document(changelogs, include_cover=False)
    assert 'id="doc-app-changelog"' in combined
    assert 'id="doc-engine-changelog"' in combined
    assert '](#doc-app-changelog)' in combined
    assert '](#doc-engine-changelog)' in combined


def test_auto_linking_of_repo_files():
    """Verify that Python files mentioned in docs are automatically linked to GitHub."""
    try:
        import sys
        from pathlib import Path
        repo_root = Path(__file__).parent.parent
        sys.path.insert(0, str(repo_root))
        from backend.app import create_app
        from bs4 import BeautifulSoup
    except ImportError as e:
        pytest.skip(f"Flask app or dependencies not available: {e}")

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        # Check a page with plain-text code file mentions outside Mermaid.
        response = client.get('/docs/documentation_page_delivery')
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
        response = client.get('/docs/osm_data')
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
        from backend.blueprints.docs import _auto_link_code_files
        with app.test_request_context():
            linked = _auto_link_code_files('```mermaid\nflowchart LR\n    D[docs.py]\n```')
        assert 'click D' in linked and '/backend/blueprints/docs.py' in linked



if __name__ == "__main__":
    # Allow running directly with python for debugging
    try:
        test_documentation_links()
        print("✅ All documentation links are valid!")
    except Exception as e:
        # pytest.fail raises an exception, catch it to print nicely or just let it crash
        # But pytest.fail is specific to pytest. 
        # If running as script, we might not have pytest context, but function uses pytest.fail
        # So we should probably mocking pytest.fail if running as script or catch it.
        # Actually easier to just adjust the test to use assert or raise SystemExit if running as script?
        # But we want to keep it simple.
        # The tool output showed pytest failure due to environment issues.
        # Let's just make it run.
        import sys
        print(e)
        sys.exit(1)
