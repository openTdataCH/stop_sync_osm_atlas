"""The rules of documentation/Documentation style guide.md that a script can decide.

Each test lists every violation with its page and line, so one run shows
everything to fix.
"""
from pathlib import Path
import re


def _pages():
    from backend.blueprints.docs import _engine_root

    roots = Path(__file__).resolve().parents[1] / 'documentation', Path(_engine_root()) / 'documentation'
    assert all(root.exists() for root in roots), f'Documentation directories not found: {roots}'
    return sorted(path for root in roots for path in root.glob('*.md'))


def _prose(path):
    """Yield (line number, text) outside code, with inline code, link targets and quotes removed."""
    in_fence = False
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
        elif not in_fence:
            line = re.sub(r'`[^`]*`', '``', line)
            line = re.sub(r'\]\([^)]*\)', ']', line)
            yield number, re.sub(r'"[^"]*"', '""', line)


def test_pages_end_with_code_and_related_pages():
    """Numbered pages end with Related pages; section pages (A2.1, E5.3) put Code just before it."""
    failures = []
    for path in _pages():
        number = re.match(r'(\d+(?:\.\d+)*)\.? ', path.name)
        contract = path.name == 'Result bundle format.md'
        if not contract and (not number or number.group(1).startswith('0')):
            continue
        headings = [line.strip() for _, line in _prose(path) if line.startswith('## ')]
        expected = ['## Code', '## Related pages'] if contract or '.' in number.group(1) else ['## Related pages']
        if headings[-len(expected):] != expected:
            failures.append(f'{path.name}: must end with {" then ".join(expected)}')
    assert not failures, '\n'.join(failures)


def test_british_spelling():
    american = re.compile(r'\b(behaviors?|behavioral|colors?|colored|centers?|centered|gray|analyz\w*)\b', re.I)
    failures = [f'{path.name}:{number}: {word}'
                for path in _pages() for number, line in _prose(path) for word in american.findall(line)]
    assert not failures, '\n'.join(failures)


def test_pages_describe_current_behaviour():
    history = re.compile(r'\b(no longer|not yet|currently|previously|originally)\b', re.I)
    failures = [f'{path.name}:{number}: {word}'
                for path in _pages() if path.name != 'Changelog.md'
                for number, line in _prose(path) for word in history.findall(line)]
    assert not failures, 'History goes in the changelogs:\n' + '\n'.join(failures)


def test_code_files_are_named_in_backticks():
    link = re.compile(r'\]\((?!https?:)[^)]*\.(py|js|mjs|css|html|json|ya?ml|toml|sh)\b')
    failures = [f'{path.name}:{number}' for path in _pages()
                for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1) if link.search(line)]
    assert not failures, 'Write code paths in backticks, not as links:\n' + '\n'.join(failures)


def test_paragraphs_are_not_hard_wrapped():
    failures = []
    for path in _pages():
        previous = False
        for number, line in _prose(path):
            prose = bool(line.strip()) and not re.match(r'\s*([-*+>|#<!]|\d+\.\s)', line) and not line.startswith('    ')
            if prose and previous:
                failures.append(f'{path.name}:{number}')
            previous = prose
    assert not failures, 'Write each paragraph on one line:\n' + '\n'.join(failures)
