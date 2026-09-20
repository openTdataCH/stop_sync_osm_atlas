import os
from pathlib import Path
import re
from urllib.parse import unquote
import pytest

def test_documentation_links():
    """
    Scans app- and engine-owned Markdown and validates relative links.
    """
    # Assuming code is running from repo root. If not, adjust or use conftest to set root.
    # Currently GitHub Action runs from repo root.
    repo_root = Path.cwd()
    docs_dirs = [repo_root / "documentation", repo_root / "engine" / "documentation"]
    missing_dirs = [str(path) for path in docs_dirs if not path.exists()]
    if missing_dirs:
        pytest.fail(f"Documentation directories not found: {', '.join(missing_dirs)}")

    broken_links = []
    total_links = 0
    
    # Sort for consistent checking order
    md_files = sorted(
        (path for docs_dir in docs_dirs for path in docs_dir.glob("*.md")),
        key=lambda path: str(path.relative_to(repo_root)).lower(),
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
            
            target = md_file.parent / clean_link
            
            if not target.exists():
                broken_links.append({
                    'file': str(md_file.relative_to(repo_root)),
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
        list((repo_root / "documentation").glob("*.md"))
        + list((repo_root / "engine" / "documentation").glob("*.md")),
        key=lambda path: str(path.relative_to(repo_root)).lower(),
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


def test_docs_portal_labels_engine_and_application_boundaries():
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        response = client.get('/docs/exact_matching')
        assert response.status_code == 200
        soup = BeautifulSoup(response.data.decode('utf-8'), 'html.parser')

        collection_labels = {
            node.get_text(' ', strip=True)
            for node in soup.select('.docs-collection-label')
        }
        assert 'Matching engine' in collection_labels
        assert 'Review application & deployment' in collection_labels
        assert 'Project overview' not in collection_labels

        overview_link = soup.find('a', href='/docs/intro')
        assert overview_link is not None
        assert overview_link.get_text(' ', strip=True) == '0. Project overview'

        overview_heading = soup.select_one('#docs-content-html > h1')
        assert overview_heading is not None
        assert overview_heading.get_text(' ', strip=True) == '0. Project overview'

        pills = soup.select('#docs-owner-pill')
        assert len(pills) == 1
        assert pills[0].get_text(' ', strip=True) == 'Engine'
        assert 'docs-owner-pill--engine' in pills[0].get('class', [])
        assert pills[0].has_attr('hidden')
        heading_owner = soup.select_one('h1 .docs-heading-owner--engine')
        assert heading_owner is not None
        assert heading_owner.select_one('.docs-heading-owner-label').get('aria-label') == 'Engine'
        assert heading_owner.select_one('.docs-heading-number').get_text(strip=True) == '2.1'
        assert heading_owner.get_text('', strip=True) == 'Engine.2.1'
        assert soup.select_one('#docs-context') is None

        for path, label, modifier in (
            ('/docs', 'Shared', 'docs-owner-pill--shared'),
            ('/docs/database', 'App', 'docs-owner-pill--app'),
        ):
            owner_response = client.get(path)
            assert owner_response.status_code == 200
            owner_soup = BeautifulSoup(owner_response.data.decode('utf-8'), 'html.parser')
            owner_pill = owner_soup.select_one('#docs-owner-pill')
            assert owner_pill is not None
            assert owner_pill.get_text(' ', strip=True) == label
            assert modifier in owner_pill.get('class', [])
            assert owner_pill.has_attr('hidden')

        partial = client.get('/docs/database', headers={'X-Docs-Partial': '1'})
        assert partial.status_code == 200
        payload = partial.get_json()
        assert payload['active_context']['key'] == 'app'
        assert payload['active_context']['repo_path'] == 'documentation/'
        assert payload['active_context']['show_owner_pill'] is False


def test_docs_portal_uses_project_scoped_section_numbers():
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        response = client.get('/docs')
        assert response.status_code == 200
        soup = BeautifulSoup(response.data.decode('utf-8'), 'html.parser')

        def scoped_nav_label(href):
            node = soup.find('a', href=href)
            assert node is not None
            owner = node.select_one('.docs-nav-owner')
            suffix = node.select_one('.docs-section-title-text').get_text(strip=True)
            prefix = owner.select_one('.docs-nav-owner-label').get_text(strip=True) if owner else ''
            number = owner.select_one('.docs-nav-owner-number').get_text(strip=True) if owner else ''
            return f'{prefix}.{number} {suffix}'.strip(), owner

        for href, expected, owner_class, expanded_label in (
            ('/docs/download_and_process_data', 'E.1 Data acquisition & processing', 'docs-nav-owner--engine', 'E'),
            ('/docs/atlas_cached_import_optimization', 'E.5.1 Atlas-Cached Import Optimization', 'docs-nav-owner--engine', 'E'),
            ('/docs/pipeline_tests', 'E.6 Engine tests', 'docs-nav-owner--engine', 'E'),
            ('/docs/database', 'A.1 Database & bundle import', 'docs-nav-owner--app', 'A'),
            ('/docs/frontend_asset_management', 'A.3.4 Frontend Asset Management', 'docs-nav-owner--app', 'A'),
            ('/docs/test', 'A.4 Web app tests', 'docs-nav-owner--app', 'A'),
            ('/docs/backend_tests', 'A.4.1 Backend Tests', 'docs-nav-owner--app', 'A'),
        ):
            label, owner = scoped_nav_label(href)
            assert label == expected
            assert owner_class in owner.get('class', [])
            assert owner.select_one('.docs-nav-owner-label').get_text('', strip=True) == expanded_label
            assert owner.select_one('.docs-nav-owner-number').get_text(strip=True)
            assert owner.find_parent('a').get('href') == href

        contributing = soup.find('a', href='/docs/contributing')
        assert contributing is not None
        assert contributing.select_one('.docs-nav-owner') is None
        assert contributing.get_text(' ', strip=True) == 'Contributing'

        web_tests_response = client.get('/docs/test')
        assert web_tests_response.status_code == 200
        web_tests_soup = BeautifulSoup(web_tests_response.data.decode('utf-8'), 'html.parser')
        web_tests_heading = web_tests_soup.select_one('h1.docs-scoped-heading')
        assert web_tests_heading is not None
        assert web_tests_heading.select_one('.docs-heading-owner-label').get('aria-label') == 'App'
        assert web_tests_heading.select_one('.docs-heading-number').get_text(strip=True) == '4'
        assert 'Web App Tests' in web_tests_heading.get_text(' ', strip=True)

        contributing_response = client.get('/docs/contributing')
        assert contributing_response.status_code == 200
        contributing_soup = BeautifulSoup(contributing_response.data.decode('utf-8'), 'html.parser')
        assert contributing_soup.select_one('h1').get_text(' ', strip=True) == 'Contributing'


def test_app_and_engine_changelogs_have_distinct_canonical_routes():
    from backend.app import create_app
    from bs4 import BeautifulSoup

    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        app_response = client.get('/docs/changelog')
        assert app_response.status_code == 200
        app_soup = BeautifulSoup(app_response.data.decode('utf-8'), 'html.parser')
        assert app_soup.select_one('#docs-owner-pill').get_text(strip=True) == 'App'
        assert not app_soup.select_one('#docs-owner-pill').has_attr('hidden')
        assert app_soup.select_one('h1').get_text(strip=True) == 'Review Application Changelog'
        assert app_soup.find('a', href='/docs/engine_changelog') is not None

        engine_response = client.get('/docs/engine_changelog')
        assert engine_response.status_code == 200
        engine_soup = BeautifulSoup(engine_response.data.decode('utf-8'), 'html.parser')
        assert engine_soup.select_one('#docs-owner-pill').get_text(strip=True) == 'Engine'
        assert not engine_soup.select_one('#docs-owner-pill').has_attr('hidden')
        assert engine_soup.select_one('h1').get_text(strip=True) == 'Matching Engine Changelog'
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
    relative = [str(path.relative_to(Path.cwd())) for path in all_docs]
    assert relative[0] == 'documentation/0. Intro.md'
    assert 'engine/documentation/2. Matching process.md' in relative
    assert 'documentation/2. Web app.md' in relative
    assert relative.index('engine/documentation/2. Matching process.md') < relative.index('documentation/2. Web app.md')

    engine_only = _sorted_docs(['engine:2'])
    assert engine_only
    assert all('engine/documentation' in str(path) for path in engine_only)
    assert {path.name for path in engine_only} >= {'2. Matching process.md', '2.1 Exact matching.md'}

    app_only = _sorted_docs(['app:2'])
    assert app_only
    assert all(path.parent == Path.cwd() / 'documentation' for path in app_only)
    assert {path.name for path in app_only} >= {'2. Web app.md', '2.8 Documentation Page Delivery.md'}

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

        # 2. Check Mermaid diagram links
        response = client.get('/docs/download_and_process_data')
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
