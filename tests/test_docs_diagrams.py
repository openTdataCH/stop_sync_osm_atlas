"""Generated documentation diagrams stay current, accessible and referenced."""
import importlib.util
from pathlib import Path
import re
from urllib.parse import unquote
import xml.etree.ElementTree as ElementTree

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
SVG_NS = '{http://www.w3.org/2000/svg}'
_IMAGE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)[^)]*\)|<img\b[^>]*\bsrc="(?P<html_src>[^"]+)"')
_FENCE = re.compile(r'^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$', re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r'(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)')


def _load_build():
    spec = importlib.util.spec_from_file_location(
        'docs_diagram_build', APP_ROOT / 'documentation' / 'diagrams' / 'build.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build()


def _engine_available():
    return (build.engine_root() / 'pyproject.toml').is_file()


RENDERED = list(build.render_all())
NAMES = [name for name, _, _, _ in RENDERED]


def _documentation_dirs():
    dirs = {'app': APP_ROOT / 'documentation'}
    if _engine_available():
        dirs['engine'] = build.engine_root() / 'documentation'
    return dirs


@pytest.mark.parametrize('name, tree, path, svg', RENDERED, ids=NAMES)
def test_committed_diagram_matches_its_source(name, tree, path, svg):
    if tree == 'engine' and not _engine_available():
        pytest.skip('engine checkout not found (set ENGINE_DIR)')
    assert path.exists(), f'{path} is missing: run python3 documentation/diagrams/build.py'
    assert path.read_text(encoding='utf-8') == svg, (
        f'{path.name} differs from documentation/diagrams/catalog.py: run python3 documentation/diagrams/build.py'
    )


@pytest.mark.parametrize('name, tree, path, svg', RENDERED, ids=NAMES)
def test_diagram_is_self_contained_and_accessible(name, tree, path, svg):
    root = ElementTree.fromstring(svg)
    assert root.tag == f'{SVG_NS}svg'
    assert root.get('role') == 'img'
    title = root.find(f'{SVG_NS}title')
    description = root.find(f'{SVG_NS}desc')
    assert title is not None and title.text and title.text.strip()
    assert description is not None and description.text and len(description.text.split()) >= 8
    assert float(root.get('width')) <= 960
    # Portal, GitHub and PDF must render the file identically.
    for forbidden in ('<style', '<script', '<foreignObject', 'href=', '@font-face', 'url('):
        assert forbidden not in svg, f'{name} contains {forbidden}'


def _markdown_images(path):
    # Examples in code are not images.
    text = _INLINE_CODE.sub('', _FENCE.sub('', path.read_text(encoding='utf-8')))
    for match in _IMAGE.finditer(text):
        source = match.group('src') or match.group('html_src')
        yield match.group('alt'), source


def test_every_referenced_image_exists_and_kit_figures_have_alt_text():
    problems = []
    kit_names = set(NAMES)
    for tree, directory in _documentation_dirs().items():
        for page in sorted(directory.glob('*.md')):
            for alt, source in _markdown_images(page):
                if source.startswith(('http://', 'https://', 'data:', '/')):
                    continue
                target = (page.parent / unquote(source.split('#', 1)[0])).resolve()
                if not target.is_file():
                    problems.append(f'{tree}: {page.name} references missing {source}')
                if target.suffix == '.svg' and target.stem in kit_names and alt is not None and not alt.strip():
                    problems.append(f'{tree}: {page.name} shows {source} without alt text')
    assert not problems, '\n'.join(problems)


def test_every_kit_diagram_is_used_by_a_page():
    dirs = _documentation_dirs()
    used = {tree: set() for tree in dirs}
    for tree, directory in dirs.items():
        for page in directory.glob('*.md'):
            for _, source in _markdown_images(page):
                used[tree].add(Path(unquote(source)).stem)
    unused = [f'{tree}: {name}' for name, tree, _, _ in RENDERED if tree in dirs and name not in used[tree]]
    assert not unused, f'Diagrams defined in catalog.py but shown on no page: {unused}'
