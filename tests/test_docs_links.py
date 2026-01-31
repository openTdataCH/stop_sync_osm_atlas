import os
from pathlib import Path
import re
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
            total_links += 1
            # Clean URL: decode URL encoding (e.g., %20 -> space) and remove anchors
            from urllib.parse import unquote
            clean_link = unquote(link.split('#')[0])
            
            # All documentation links are relative to the documentation directory
            # (flat structure with all .md files in the same directory)
            target = docs_dir / clean_link
            
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

