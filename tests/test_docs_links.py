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
