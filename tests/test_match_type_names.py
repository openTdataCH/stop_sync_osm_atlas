"""Match type names live in one file: backend/services/matching_rules.py.

The engine names match types, some after the dataset profile (``uic_`` for
Switzerland), and renames them when the profile changes. Keeping every spelling in
one file makes such a change one edit. The engine import contract
(tests/test_engine_import_contract.py) fails when that file misses a name the engine
writes; these tests keep the rest of the application pointing at that file.
"""
import ast
from pathlib import Path
import re

from backend.services.matching_rules import ALL_MATCH_TYPES, match_types_for_filter

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'backend/services/matching_rules.py'


def test_only_the_rule_catalog_spells_match_types():
    typed = []
    for path in sorted((ROOT / 'backend').rglob('*.py')):
        if path == CATALOG:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Constant) and node.value in ALL_MATCH_TYPES:
                typed.append(f'{path.relative_to(ROOT)}:{node.lineno} {node.value!r}')
    assert not typed, (
        'These lines type a match type by hand:\n  ' + '\n  '.join(typed) + '\n'
        'The engine names match types, some after the dataset profile, and renames them '
        'when the profile changes. Copy `method` from the bundle match, tell rows apart '
        'by stop_type, or look the types up by rule key with match_types_for_filter() '
        'from backend/services/matching_rules.py.'
    )


def test_every_matched_filter_of_the_map_selects_match_types():
    """A filter value unknown to the catalog would silently select nothing."""
    template = (ROOT / 'templates/pages/index.html').read_text(encoding='utf-8')
    script = (ROOT / 'static/js/pages/filters.js').read_text(encoding='utf-8')
    values = (re.findall(r'class="filter-(?:match|route|distance)-method[^"]*"[^>]*\bvalue="([^"]+)"', template)
              + re.findall(r"\{ value: '([^']+)', selector:", script))
    assert len(values) >= 20, 'The patterns no longer find the Matched filters'
    unknown = sorted({value for value in values if not match_types_for_filter(value)})
    assert not unknown, (
        f'Matched filters with values backend/services/matching_rules.py does not know: {unknown}. '
        'Use a rule key or match type from that file, in templates/pages/index.html and '
        'MATCH_METHOD_FILTERS in static/js/pages/filters.js.'
    )
