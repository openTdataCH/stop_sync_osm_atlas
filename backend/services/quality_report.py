"""Render generated quality evidence without turning missing measurements green."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.parse import quote

PLACEHOLDER = '{{CODE_QUALITY_REPORT}}'


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
    generated = {'quality/latest.json', 'quality/quality-map.json', 'quality/report.md'}
    for name in sorted(set(result.stdout.decode().rstrip('\0').split('\0'))):
        if not name or name in generated or name.startswith(('quality/raw/', 'documentation/generated/')):
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


def render_report(report, artifact_prefix=''):
    """Plain Markdown: usable as an artifact and in the existing docs reader."""
    revisions = report.get('revision', {})
    prefix = artifact_prefix
    lines = [f"Evidence: **{report.get('completeness', 'unavailable')}**. Generated: {report.get('generated_at', 'unknown')}.", '',
             f"App revision: `{revisions.get('app')}`. Engine revision: `{revisions.get('engine')}`.", '',
             'Tools: ' + (', '.join(f'{_cell(name)} {_cell(version)}' for name, version in sorted(report.get('tools', {}).items())) or 'not recorded') + '.', '',
             'Missing measurements are explicit. Coverage targets and trends are advisory during baseline collection. There is no combined quality score.', '',
             '| Module | Risk | Tests | Branch coverage | Mutation | Clones | Python dead code | Docs | Architecture | Trend |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for mid, row in sorted(report.get('modules', {}).items()):
        docs = row['docs']
        values = [mid, row['criticality'], _metric(row['tests']), _metric(row['coverage'], 'branches'), _metric(row['mutation']),
                  f"{row['duplication']['count']} ({_metric(row['duplication'])})" if row['duplication'].get('count') is not None else _metric(row['duplication']),
                  f"{row['dead_code']['count']} ({_metric(row['dead_code'])})" if row['dead_code'].get('count') is not None else _metric(row['dead_code']),
                  f"{docs.get('satisfied', 0)}/{docs.get('required', 0)}", _metric(row['architecture']), _metric(row.get('trend', {}))]
        lines.append('| ' + ' | '.join(_cell(value) for value in values) + ' |')
    lines.extend(['', 'Required check results from the recorded run:', ''])
    checks = report.get('checks', [])
    if not checks:
        lines.append('Not measured. Run `make quality` to collect supported evidence.')
    for check in checks:
        lines.append(f"- **{_cell(check.get('name', 'unknown'))}**: {_cell(check.get('status', 'not_measured'))}")
    lines.extend(['', 'Raw evidence:', ''])
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
        for lane in ('tests', 'coverage', 'mutation', 'duplication', 'dead_code', 'docs', 'architecture', 'trend'):
            measurement = row.get(lane, {} if lane == 'trend' else None)
            if not isinstance(measurement, dict) or not isinstance(measurement.get('status', 'not_measured'), str):
                raise ValueError(f'Invalid quality {lane} measurement')


def replace_quality_placeholder(text, repo_root, artifact_prefix='/docs/quality-artifacts/'):
    if PLACEHOLDER not in text:
        return text
    root = Path(repo_root)
    path = root / 'quality/latest.json'
    try:
        report = json.loads(path.read_text())
        _validate_render_shape(report)
        age = datetime.now(timezone.utc) - datetime.fromisoformat(report['generated_at'])
        stale = age.total_seconds() > 7 * 86400 or age.total_seconds() < -300
        # Images may omit .git. Be explicit about that verification limitation.
        fingerprint = source_fingerprint(root)
        warning = ''
        if fingerprint is not None:
            stale |= fingerprint != report.get('fingerprints', {}).get('app')
        else:
            warning = 'Checkout inputs cannot be verified in this deployment. The recorded revisions identify this evidence.\n\n'
        configured = Path(os.environ['ENGINE_DIR']) if os.environ.get('ENGINE_DIR') else None
        if configured is not None and not configured.is_absolute():
            configured = (root / configured).resolve()
        engine = next((candidate for candidate in (configured, root / 'engine', root.parent / 'engine')
                       if candidate is not None and (candidate / 'pyproject.toml').is_file()), None)
        engine_fingerprint = source_fingerprint(engine) if engine else None
        if engine_fingerprint is not None:
            stale |= engine_fingerprint != report.get('fingerprints', {}).get('engine')
        elif any(mid.startswith('engine.') for mid in report['modules']):
            warning += 'Engine checkout inputs cannot be verified in this deployment.\n\n'
        if stale:
            report['completeness'] = 'stale'
            for row in report['modules'].values():
                for lane in ('tests', 'coverage', 'mutation', 'duplication', 'dead_code', 'architecture', 'trend'):
                    if lane in row and row[lane].get('status') not in {'not_measured', 'not_applicable'}:
                        row[lane]['status'] = 'stale'
        rendered = warning + render_report(report, artifact_prefix)
    except (OSError, ValueError, KeyError, TypeError):
        rendered = '**Quality evidence unavailable.** Run `make quality` and publish its generated artifacts. Missing evidence is not a passing result.'
    return text.replace(PLACEHOLDER, rendered)
