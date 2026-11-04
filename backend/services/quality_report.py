"""Render generated quality evidence without turning missing measurements green."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
from urllib.parse import quote

PLACEHOLDER = '{{CODE_QUALITY_REPORT}}'
# Written by `make deploy-report` and committed, so a deployment built from the checkout carries it.
PUBLISHED = 'quality/published'
# What the dockerfile copies into the app image: the code a deployment runs.
SHIPPED_ROOTS = ('backend', 'templates', 'static', 'migrations', 'config', 'documentation')
SHIPPED_FILES = ('README.md', 'LICENSE', 'entrypoint.sh', 'engine.ref')
# Kept in a developer checkout but ignored by Git and Docker, so never committed or shipped.
LOCAL_ONLY_FILES = ('documentation/Documentation style guide.md',)


def _is_shipped(name):
    parts = name.split('/')
    if name in LOCAL_ONLY_FILES or (name not in SHIPPED_FILES and parts[0] not in SHIPPED_ROOTS):
        return False
    return not (name.startswith('documentation/generated/') or '__pycache__' in parts
                or parts[-1] == '.DS_Store' or name.endswith('.pyc'))


def shipped_fingerprint(files):
    """Hash (name, content) pairs of shipped files, read from a commit, a checkout or an image."""
    digest = hashlib.sha256()
    for name, content in sorted(item for item in files if _is_shipped(item[0])):
        digest.update(name.encode() + b'\0' + content + b'\0')
    return digest.hexdigest()


def shipped_files(root):
    """Shipped files on disk. Needs no Git, because images omit .git."""
    root = Path(root)
    for top in (*SHIPPED_ROOTS, *SHIPPED_FILES):
        base = root / top
        for path in [base] if base.is_file() else base.rglob('*'):
            if path.is_file() and not path.is_symlink():
                yield path.relative_to(root).as_posix(), path.read_bytes()


def source_fingerprint(root):
    """Hash Git's tracked and new nonignored inputs, excluding generated evidence."""
    root = Path(root)
    try:
        result = subprocess.run(['git', '-c', f'safe.directory={root}', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], capture_output=True)
    except OSError:
        return None
    if result.returncode:
        return None
    digest = hashlib.sha256()
    generated = {'quality/latest.json', 'quality/quality-map.json', 'quality/code-map.json', 'quality/report.md'}
    for name in sorted(set(result.stdout.decode().rstrip('\0').split('\0'))):
        if not name or name in generated or name.startswith(('quality/raw/', f'{PUBLISHED}/', 'documentation/generated/')):
            continue
        path = root / name
        if path.is_file() and not path.is_symlink():
            digest.update(name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _metric(item, field=None):
    status = item.get('status', 'not_measured')
    if status not in {'measured', 'pass'} or field is None:
        return status.replace('_', ' ')
    value = item.get(field)
    return f'{value}%' if value is not None else 'not applicable'


def render_report(report, artifact_prefix='', evidence_url=None):
    """Plain Markdown: usable as an artifact and in the existing docs reader.

    ``evidence_url`` replaces the raw file list with a link to the CI run that holds those files.
    """
    revisions = report.get('revision', {})
    prefix = artifact_prefix
    lines = [f"Evidence: **{report.get('completeness', 'unavailable')}**. Generated: {report.get('generated_at', 'unknown')}.", '',
             f"App revision: `{revisions.get('app')}`. Engine revision: `{revisions.get('engine')}`.", '',
             'Tools: ' + (', '.join(f'{_cell(name)} {_cell(version)}' for name, version in sorted(report.get('tools', {}).items())) or 'not recorded') + '.', '',
             'Missing measurements are explicit. Criticality is declared in the module catalog from the impact of a failure, not measured. '
             'Duplicated blocks counts code clones of at least 10 lines; "pass" means none is new since the reviewed baseline. '
             'There is no combined quality score.', '',
             '| Module | Criticality | Tests | Branch coverage | Mutation | Duplicated blocks | Python dead code | Docs | Architecture |',
             '|---|---|---|---|---|---|---|---|---|']
    for mid, row in sorted(report.get('modules', {}).items()):
        docs = row['docs']
        values = [mid, row['criticality'], _metric(row['tests']), _metric(row['coverage'], 'branches'), _metric(row['mutation']),
                  f"{row['duplication']['count']} ({_metric(row['duplication'])})" if row['duplication'].get('count') is not None else _metric(row['duplication']),
                  f"{row['dead_code']['count']} ({_metric(row['dead_code'])})" if row['dead_code'].get('count') is not None else _metric(row['dead_code']),
                  f"{docs.get('satisfied', 0)}/{docs.get('required', 0)}", _metric(row['architecture'])]
        lines.append('| ' + ' | '.join(_cell(value) for value in values) + ' |')
    lines.extend(['', 'Required check results from the recorded run:', ''])
    checks = report.get('checks', [])
    if not checks:
        lines.append('Not measured. Run `make quality` to collect supported evidence.')
    for check in checks:
        lines.append(f"- **{_cell(check.get('name', 'unknown'))}**: {_cell(check.get('status', 'not_measured'))}")
    lines.extend(['', 'Raw evidence:', ''])
    if evidence_url:
        lines.append(f"Test results, coverage and analyzer outputs are in the [CI run]({evidence_url}) that produced this report, "
                     f"as the artifact `quality-{_cell(revisions.get('app'))}`. GitHub keeps it for 30 days.")
    else:
        for path in report.get('artifacts', []):
            lines.append(f'- `{_cell(path)}`' if prefix is None else f'- [{_cell(path)}]({prefix}{quote(path, safe="/")})')
        if not report.get('artifacts'):
            lines.append('Not measured.')
    lines.extend(['', 'For invariants, tests, documentation and dependency context, run `python scripts/quality.py context MODULE_ID`. '
                  'Use `impact PATH` or `symbol NAME --depth 1` for bounded navigation. Python imports are syntax evidence; dynamic calls and JavaScript symbols are heuristic.', ''])
    return '\n'.join(lines)


def _validate_render_shape(report):
    """Reject malformed optional artifacts without adding a runtime schema dependency."""
    if not isinstance(report, dict) or report.get('schema_version') != 1 or not isinstance(report.get('modules'), dict):
        raise ValueError('unsupported quality artifact')
    for field in ('revision', 'fingerprints', 'tools'):
        if not isinstance(report.get(field, {}), dict):
            raise ValueError(f'Invalid quality {field}')
    if not isinstance(report.get('checks', []), list) or any(not isinstance(check, dict) for check in report.get('checks', [])):
        raise ValueError('Invalid quality checks')
    if not isinstance(report.get('artifacts', []), list) or any(not isinstance(path, str) for path in report.get('artifacts', [])):
        raise ValueError('Invalid quality artifact links')
    for row in report['modules'].values():
        if not isinstance(row, dict):
            raise ValueError('Invalid quality module')
        for lane in ('tests', 'coverage', 'mutation', 'duplication', 'dead_code', 'docs', 'architecture'):
            measurement = row.get(lane)
            if not isinstance(measurement, dict) or not isinstance(measurement.get('status', 'not_measured'), str):
                raise ValueError(f'Invalid quality {lane} measurement')


def load_published(repo_root):
    """The published report and code map, marked stale when the running code is not what they measured.

    Returns ``(report, code_map, publication, changed)``; ``code_map`` is None for a report published without one.
    Raises OSError, ValueError, KeyError or TypeError when the published evidence is missing or malformed.
    """
    root = Path(repo_root)
    report = json.loads((root / PUBLISHED / 'latest.json').read_text())
    _validate_render_shape(report)
    publication = json.loads((root / PUBLISHED / 'publication.json').read_text())
    try:
        code_map = json.loads((root / PUBLISHED / 'code-map.json').read_text())
    except FileNotFoundError:
        code_map = None
    if code_map is not None and (not isinstance(code_map, dict) or code_map.get('schema_version') != 1):
        raise ValueError('unsupported code map')
    changed = []
    # The report commit itself only touches quality/published, which is not shipped code.
    if publication['shipped_fingerprint'] != shipped_fingerprint(shipped_files(root)):
        changed.append('the application code')
    if report['revision'].get('engine') != (root / 'engine.ref').read_text().strip():
        changed.append('the pinned engine')
    if changed:
        report['completeness'] = 'stale'
        for row in report['modules'].values():
            for lane in ('tests', 'coverage', 'mutation', 'duplication', 'dead_code', 'architecture'):
                if lane in row and row[lane].get('status') not in {'not_measured', 'not_applicable'}:
                    row[lane]['status'] = 'stale'
        for check in report.get('checks', []):
            check['status'] = 'stale'
    return report, code_map, publication, changed


def stale_warning(report, changed):
    measured = str(report['revision'].get('app'))[:7]
    return (f"This report was measured on app commit `{measured}`. Since then {' and '.join(changed)} changed, "
            'so it may not describe the code running here. Run `make deploy-report` once CI has passed on the latest commit.')


def replace_quality_placeholder(text, repo_root):
    """Show the published report, with a warning when the running code is not what it measured."""
    if PLACEHOLDER not in text:
        return text
    try:
        report, _, publication, changed = load_published(repo_root)
        warning = f'> [!WARNING]\n> {stale_warning(report, changed)}\n\n' if changed else ''
        rendered = warning + render_report(report, None, publication.get('run_url'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        rendered = ('**Quality evidence unavailable.** Run `make deploy-report` once CI has passed on the latest commit. '
                    'Missing evidence is not a passing result.')
    return text.replace(PLACEHOLDER, rendered)
