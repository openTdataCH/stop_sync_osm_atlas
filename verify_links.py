import os
import re
from pathlib import Path
from urllib.parse import unquote

def test_documentation_links():
    repo_root = Path.cwd()
    docs_dir = repo_root / "documentation"
    readme_file = repo_root / "README.md"
    
    broken_links = []
    
    # Check README.md
    if readme_file.exists():
        with open(readme_file, 'r', encoding='utf-8') as f:
            content = f.read()
            links = re.findall(r'\[[^\]]+\]\(([^)]+\.md[^)]*)\)', content)
            for link in links:
                clean_link = unquote(link.split('#')[0])
                target = (repo_root / clean_link).resolve()
                if not target.exists():
                    broken_links.append(f"README.md -> {link} (Target: {target})")

    # Check documentation dir
    if docs_dir.exists():
        for md_file in docs_dir.glob("*.md"):
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                links = re.findall(r'\[[^\]]+\]\(([^)]+\.md[^)]*)\)', content)
                for link in links:
                    clean_link = unquote(link.split('#')[0])
                    target = (docs_dir / clean_link).resolve()
                    if not target.exists():
                        broken_links.append(f"{md_file.name} -> {link} (Target: {target})")

    if broken_links:
        print("FAIL: Broken links found:")
        for bl in broken_links:
            print(f"  {bl}")
        return False
    else:
        print("PASS: No broken documentation links!")
        return True

if __name__ == "__main__":
    test_documentation_links()
