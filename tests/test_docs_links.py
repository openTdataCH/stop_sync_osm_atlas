import os
from pathlib import Path
import re
from urllib.parse import unquote
import pytest

def test_documentation_links():
    """
    Scans all markdown files in the documentation directory and validates that
    all relative links point to existing files.
    """
    # Assuming code is running from repo root. If not, adjust or use conftest to set root.
    # Currently GitHub Action runs from repo root.
    repo_root = Path.cwd()
    docs_dir = repo_root / "documentation"
    
    if not docs_dir.exists():
        pytest.fail(f"Documentation directory not found at {docs_dir}")

    broken_links = []
    total_links = 0
    
    # Sort for consistent checking order
    md_files = sorted(docs_dir.glob("*.md"))
    
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
            
            # All documentation links are relative to the documentation directory
            # (flat structure with all .md files in the same directory)
            target = md_file.parent / clean_link
            
            if not target.exists():
                broken_links.append({
                    'file': md_file.name,
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
    docs_files = sorted((repo_root / "documentation").glob("*.md"), key=lambda path: path.name.lower())

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
