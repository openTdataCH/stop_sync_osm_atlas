"""Render the documentation diagrams to SVG.

Usage, from the review application repository root::

    python3 documentation/diagrams/build.py            # write every diagram
    python3 documentation/diagrams/build.py --check    # fail if any file is stale
    python3 documentation/diagrams/build.py --only architecture-system

Diagrams of the engine documentation are written into the sibling engine
checkout (``ENGINE_DIR``, ``engine/`` or ``../engine``), like the Mermaid
pre-renderer, so each documentation tree commits its own images. Only the
Python standard library is required.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog import DIAGRAMS  # noqa: E402


def engine_root() -> Path:
    configured = os.getenv('ENGINE_DIR', '').strip()
    candidates = []
    if configured:
        path = Path(configured)
        candidates.append(path if path.is_absolute() else APP_ROOT / path)
    candidates += [APP_ROOT / 'engine', APP_ROOT.parent / 'engine']
    for candidate in candidates:
        if (candidate / 'pyproject.toml').is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def output_path(tree: str, name: str) -> Path:
    if tree == 'app':
        return APP_ROOT / 'documentation' / 'images' / f'{name}.svg'
    if tree == 'engine':
        return engine_root() / 'documentation' / 'images' / f'{name}.svg'
    raise ValueError(f'Unknown documentation tree {tree!r}')


def render_all(only=None):
    """Yield ``(name, tree, path, svg)`` for the selected diagrams."""
    for name, tree, build in DIAGRAMS:
        if only and name not in only:
            continue
        yield name, tree, output_path(tree, name), build().render()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='Report stale or missing files without writing')
    parser.add_argument('--only', nargs='+', metavar='NAME', help='Render only these diagrams')
    args = parser.parse_args(argv)

    known = {name for name, _, _ in DIAGRAMS}
    unknown = sorted(set(args.only or ()) - known)
    if unknown:
        parser.error(f'unknown diagram(s): {", ".join(unknown)}')

    stale = []
    for name, tree, path, svg in render_all(args.only):
        if tree == 'engine' and not (engine_root() / 'pyproject.toml').is_file():
            print(f'skip   {name}: engine checkout not found (set ENGINE_DIR)')
            continue
        current = path.read_text(encoding='utf-8') if path.exists() else None
        if current == svg:
            print(f'ok     {path.relative_to(path.parents[2])}')
            continue
        if args.check:
            stale.append(path)
            print(f'stale  {path}')
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding='utf-8')
        print(f'wrote  {path.relative_to(path.parents[2])}')
    if stale:
        print('Run: python3 documentation/diagrams/build.py', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
