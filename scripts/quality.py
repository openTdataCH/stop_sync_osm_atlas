#!/usr/bin/env python3
"""Small, local quality catalog, evidence and navigation CLI. No service required."""
from __future__ import annotations

import argparse
import ast
from datetime import date, datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.version import engine_dir  # noqa: E402

CODE_SUFFIXES = {'.py', '.js', '.mjs', '.cjs', '.css', '.html', '.sql', '.sh', '.yml', '.yaml', '.json', '.toml'}


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def git(root, *args):
    result = subprocess.run(['git', '-c', f'safe.directory={root}', '-C', str(root), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def revision(root):
    return git(root, 'rev-parse', 'HEAD') if root else None


def repository_fingerprint(root):
    """Hash tracked and new nonignored inputs, so dirty runs cannot reuse old evidence."""
    from backend.services.quality_report import source_fingerprint
    return source_fingerprint(root)


def matches(path, pattern):
    # **/ also matches zero directory levels, unlike fnmatch alone.
    return fnmatch.fnmatchcase(path, pattern) or ('**/' in pattern and matches(path, pattern.replace('**/', '', 1)))


def excluded(path, rules):
    return any(matches(path, rule['pattern']) for rule in rules)


def schema_validate(value, schema):
    from jsonschema import Draft202012Validator
    errors = sorted(Draft202012Validator(read_json(schema)).iter_errors(value), key=lambda error: str(error.path))
    if errors:
        raise ValueError('; '.join(f'{list(error.path)}: {error.message}' for error in errors))


def source_files(root, catalog, exclusions):
    result = set()
    discovered = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
    if discovered is not None:
        result.update(name for name in discovered.rstrip('\0').split('\0')
                      if Path(name).suffix in CODE_SUFFIXES and (root / name).is_file() and not (root / name).is_symlink())
    for directory in catalog.get('source_roots', ['src']):
        result.update(path.relative_to(root).as_posix() for path in (root / directory).rglob('*')
                      if path.is_file() and not path.is_symlink() and path.suffix in CODE_SUFFIXES)
    result.update(name for name in catalog.get('source_files', []) if (root / name).is_file())
    return sorted(path for path in result if not excluded(path, exclusions + catalog.get('exclusions', [])))


def load_catalogs(engine_root=None):
    roots = {'app': ROOT}
    if engine_root:
        roots['engine'] = Path(engine_root).resolve()
    exclusions = read_json(ROOT / 'quality/exclusions.json')['source']
    catalogs, ownership = {}, {}
    for repo, root in roots.items():
        catalog = read_json(root / 'quality/modules.yml')
        if catalog is None:
            raise ValueError(f'Missing {repo} catalog: {root}/quality/modules.yml')
        schema_validate(catalog, ROOT / 'quality/modules.schema.json')
        catalogs[repo] = catalog
        for path in source_files(root, catalog, exclusions):
            owners = [module['id'] for module in catalog['modules'] if any(matches(path, glob) for glob in module['paths']['source'])]
            if len(owners) != 1:
                raise ValueError(f'{repo}:{path} needs exactly one owner, found {owners}')
            ownership[(repo, path)] = owners[0]
    return roots, catalogs, ownership


def import_bindings(tree, module_name):
    """Yield (bound name, module, imported attribute, line) for every Python import."""
    package = module_name.rsplit('.', 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.asname, alias.name, None, node.lineno
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ''
            if node.level:
                parents = package.split('.')
                prefix = '.'.join(parents[:len(parents) - node.level + 1] + ([prefix] if prefix else []))
            for alias in node.names:
                yield alias.asname or alias.name, prefix, alias.name, node.lineno


def import_names(tree, module_name):
    seen = set()
    for _, module, attribute, line in import_bindings(tree, module_name):
        for name in [module] + ([f'{module}.{attribute}'] if attribute else []):
            if (name, line) not in seen:
                seen.add((name, line))
                yield name, line


def python_module(path):
    return path.removeprefix('src/').removesuffix('.py').replace('/', '.').removesuffix('.__init__')


def import_context(path):
    name = python_module(path)
    return name + '.__init__' if path.endswith('/__init__.py') else name


def entrypoint_exists(root, name, symbol, seen=None):
    seen = set() if seen is None else seen
    if (name, symbol) in seen:
        return False
    seen.add((name, symbol))
    stem = name.replace('.', '/')
    paths = [base / suffix for base in (root, root / 'src') for suffix in (stem + '.py', stem + '/__init__.py')]
    path = next((path for path in paths if path.is_file()), None)
    if path is None:
        return False
    tree = ast.parse(path.read_text())
    if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol.split('.')[0] for node in tree.body):
        return True
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == symbol:
                    context = name + '.__init__' if path.name == '__init__.py' else name
                    imported = next(import_names(ast.Module(body=[node], type_ignores=[]), context))[0]
                    if entrypoint_exists(root, imported, alias.name, seen):
                        return True
    return False


def architecture(roots, ownership):
    violations = []
    for (repo, path), owner in ownership.items():
        if not path.endswith('.py'):
            continue
        for name, line in import_names(ast.parse((roots[repo] / path).read_text()), import_context(path)):
            forbidden = repo == 'app' and name.split('.')[0] in {'osm_public_transport_matcher', 'matching_and_import_db'}
            forbidden |= repo == 'engine' and name.split('.')[0] in {'backend', 'flask', 'sqlalchemy', 'geoalchemy2'}
            forbidden |= owner == 'engine.core-matching' and any(name == prefix or name.startswith(prefix + '.') for prefix in (
                'osm_public_transport_matcher.acquisition', 'osm_public_transport_matcher.adapters', 'osm_public_transport_matcher.integrations', 'osm_public_transport_matcher.profiles', 'osm_public_transport_matcher.results',
            ))
            if forbidden:
                violations.append({'module': owner, 'file': path, 'line': line, 'import': name})
    return violations


def module_items(catalogs):
    return [(repo, module) for repo, catalog in catalogs.items() for module in catalog['modules']]


def active_exceptions(module_ids):
    exceptions = read_json(ROOT / 'quality/exceptions.json', [])
    for item in exceptions:
        required = {'module', 'finding', 'owner', 'reason', 'expires'}
        if not required <= item.keys() or any(not item[key] for key in required):
            raise ValueError('Exceptions need module, finding, owner, reason and expires')
        if item['module'] not in module_ids or date.fromisoformat(item['expires']) < date.today():
            raise ValueError(f'Unknown module or expired exception: {item}')
    return exceptions


def check(roots, catalogs, ownership):
    items = module_items(catalogs)
    ids = [module['id'] for _, module in items]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate module ID')
    for repo, module in items:
        root = roots[repo]
        if module['criticality'] in {'critical', 'high'} and (not module['invariants'] or not module['docs'].get('explanation')):
            raise ValueError(f"{module['id']}: risk requires invariants and explanation")
        if module['criticality'] == 'critical' and not module['docs'].get('reference'):
            raise ValueError(f"{module['id']}: critical module needs reference documentation")
        date.fromisoformat(module['reviewed'])
        for kind, paths in module['docs'].items():
            for path in paths:
                if not (root / path).is_file():
                    raise ValueError(f"{module['id']}: missing {kind} documentation {path}")
        for pattern in module['paths']['tests']:
            if not list(root.glob(pattern)):
                raise ValueError(f"{module['id']}: test pattern matches nothing: {pattern}")
        for dependency in module.get('dependencies', []):
            if dependency not in ids:
                raise ValueError(f"{module['id']}: unknown dependency {dependency}")
        for entry in module['entrypoints']:
            if ':' not in entry:
                continue
            name, symbol = entry.split(':', 1)
            if not entrypoint_exists(root, name, symbol):
                raise ValueError(f"{module['id']}: missing entrypoint {entry}")
    for repo, catalog in catalogs.items():
        for contract in catalog.get('contracts', []):
            endpoints = contract['producers'] + contract['consumers']
            if not contract['producers'] or not contract['consumers'] or any(item not in ids for item in endpoints):
                raise ValueError(f"Incomplete contract endpoints: {contract['id']} (supply --engine-dir)")
            for path in contract['docs'] + contract['tests']:
                if not (roots[repo] / path).exists():
                    raise ValueError(f"Missing contract evidence: {path}")
    active_exceptions(ids)
    violations = architecture(roots, ownership)
    if violations:
        raise ValueError('Forbidden dependencies: ' + json.dumps(violations))
    return f'{len(ids)} modules, {len(ownership)} source files; ownership, references and architecture pass'


def relative_report_path(name, root):
    path = Path(name)
    if path.is_absolute():
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            # CI checkout prefixes differ from the computer rendering the report.
            for marker in ('/backend/', '/static/js/', '/src/osm_public_transport_matcher/', '/tests/'):
                if marker in name:
                    return marker[1:] + name.split(marker, 1)[1]
            return None
    return name.removeprefix('./')


def coverage_files(raw, root, javascript=False):
    if javascript:
        files = {}
        for name, data in raw.items():
            path = relative_report_path(name, root)
            statements = data.get('statementMap', {})
            line_hits = {}
            for key, value in data.get('s', {}).items():
                line = statements[key]['start']['line']
                line_hits[line] = max(value, line_hits.get(line, 0))
            branches = [hit for values in data.get('b', {}).values() for hit in values]
            files[path] = dict(lines=len(line_hits), covered_lines=sum(hit > 0 for hit in line_hits.values()),
                               branches=len(branches), covered_branches=sum(hit > 0 for hit in branches),
                               executed_lines=[line for line, hit in line_hits.items() if hit], measured_lines=list(line_hits))
        return files
    if not raw.get('meta', {}).get('branch_coverage'):
        raise ValueError('Python report was not collected with branch coverage')
    return {relative_report_path(name, root): dict(lines=data['summary']['num_statements'],
            covered_lines=data['summary']['covered_lines'], branches=data['summary']['num_branches'],
            covered_branches=data['summary']['covered_branches'], executed_lines=data['executed_lines'],
            measured_lines=data['executed_lines'] + data['missing_lines']) for name, data in raw['files'].items()}


def percent(covered, total):
    return round(100 * covered / total, 2) if total else None


def coverage_sanity(roots, ownership):
    """Fail required checks when collection is incomplete or belongs to old inputs."""
    raw_dir = ROOT / 'quality/raw'
    manifest = read_json(raw_dir / 'checks.json', {})
    if manifest.get('fingerprints') != {repo: repository_fingerprint(root) for repo, root in roots.items()}:
        raise ValueError('Coverage evidence does not match current source inputs; rerun make quality')
    checked = 0
    for repo, name, js in [('app', 'app-python-coverage.json', False), ('engine', 'engine-python-coverage.json', False), ('app', 'javascript-coverage.json', True)]:
        if repo not in roots:
            raise ValueError(f'{repo}: checkout required for coverage sanity')
        raw = read_json(raw_dir / name)
        if not raw:
            raise ValueError(f'Missing coverage artifact: {name}')
        files = coverage_files(raw, roots[repo], js)
        prefix = 'static/js/' if js else 'backend/' if repo == 'app' else 'src/'
        suffix = '.js' if js else '.py'
        expected = {path for r, path in ownership if r == repo and path.startswith(prefix) and path.endswith(suffix)}
        missing = sorted(expected - files.keys())
        if missing:
            raise ValueError(f'{name}: missing production files: {missing}')
        if not expected or not sum(files[path]['covered_lines'] for path in expected):
            raise ValueError(f'{name}: no executed production statements')
        for path in expected:
            row = files[path]
            for total, covered in [('lines', 'covered_lines'), ('branches', 'covered_branches')]:
                if not 0 <= row[covered] <= row[total]:
                    raise ValueError(f'{name}: invalid {total} totals for {path}')
        checked += len(expected)
    return f'Coverage sanity passes for {checked} production files across Python and JavaScript'


def testcase_file(attributes, root=None):
    if attributes.get('file'):
        return attributes['file']
    parts = attributes.get('classname', '').split('.')
    if root is not None:
        for length in range(len(parts), 0, -1):
            candidate = '/'.join(parts[:length]) + '.py'
            if (Path(root) / candidate).is_file():
                return candidate
    # Pytest's default xunit2 format omits `file` and appends test classes to
    # `classname`. Keep normal test-module names portable across checkouts.
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].startswith('test_'):
            return '/'.join(parts[:index + 1]) + '.py'
    return '/'.join(parts) + '.py'


def test_results(path, javascript=False, root=None):
    if not path.exists():
        return []
    if javascript:
        raw = read_json(path)
        return [{'file': row['name'], 'failed': row['status'] != 'passed', 'skipped': sum(a['status'] in {'pending', 'todo', 'disabled'} for a in row['assertionResults']),
                 'count': len(row['assertionResults'])} for row in raw.get('testResults', [])]
    return [{'file': testcase_file(row.attrib, root),
             'test_id': f"{row.attrib.get('classname', '')}::{row.attrib['name']}" if row.attrib.get('name') else None,
             'failed': row.find('failure') is not None or row.find('error') is not None,
             'skipped': int(row.find('skipped') is not None), 'count': 1} for row in ET.parse(path).iter('testcase')]


def changed_lines(root, base):
    if not base:
        return None
    diff = git(root, 'diff', '--unified=0', base, '--')
    if diff is None:
        raise ValueError(f'Cannot resolve coverage comparison base {base!r} in {root}')
    result, current = {}, None
    for line in diff.splitlines():
        if line.startswith('+++ b/'):
            current = line[6:]
        elif current and line.startswith('@@'):
            match = re.search(r'\+(\d+)(?:,(\d+))?', line)
            start, count = int(match[1]), int(match[2] or 1)
            result.setdefault(current, set()).update(range(start, start + count))
    # Local impact checks must include new files before the user stages them.
    untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z') or ''
    for name in untracked.rstrip('\0').split('\0'):
        path = root / name
        if name and path.suffix in CODE_SUFFIXES and path.is_file():
            result[name] = set(range(1, len(path.read_text().splitlines()) + 1))
    return result


def mutation_evidence(path, engine_root):
    if engine_root is None or not path.exists():
        return {'status': 'not_measured'}
    try:
        data = read_json(path)
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('Unsupported mutation evidence')
        if not isinstance(data.get('source_path'), str) or not isinstance(data.get('tests_sha256'), dict) or not data['tests_sha256']:
            raise ValueError('Missing mutation source/test provenance')
        scope = data.get('scope')
        if not isinstance(scope, str) or not scope.startswith('osm_public_transport_matcher.results.validation.'):
            raise ValueError('Mutation evidence belongs to another module')
        expected = {data['source_path']: data.get('source_sha256'), **data['tests_sha256']}
        if len(expected) != 1 + len(data['tests_sha256']) or any(not isinstance(name, str) or not name or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) for name, digest in expected.items()):
            raise ValueError('Invalid mutation source/test digests')
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(data['started_at'])).total_seconds()
        fresh = -300 <= age <= 7 * 86400
        for name, digest in expected.items():
            file = (engine_root / name).resolve()
            if not file.is_relative_to(engine_root.resolve()):
                raise ValueError('Mutation evidence path escapes checkout')
            fresh &= hashlib.sha256(file.read_bytes()).hexdigest() == digest
        total, counts = data['total_mutants'], data['counts']
        if type(total) is not int or total <= 0 or not isinstance(counts, dict) or any(type(value) is not int or value < 0 for value in counts.values()):
            raise ValueError('Invalid mutation totals')
        killed = counts.get('killed', 0)
        if sum(counts.values()) != total or killed > total:
            raise ValueError('Invalid mutation totals')
    except (OSError, KeyError, TypeError, ValueError):
        return {'status': 'invalid', 'artifact': 'raw/engine-mutation.json'}
    return {'status': 'measured' if fresh else 'stale', 'scope': scope, 'killed': killed,
            'total': total, 'score': percent(killed, total), 'artifact': 'raw/engine-mutation.json'}


def report(roots, catalogs, ownership, base=None):
    raw_dir = ROOT / 'quality/raw'
    manifest = read_json(raw_dir / 'checks.json', {})
    revisions = {repo: revision(roots.get(repo)) for repo in ('app', 'engine')}
    fingerprints = {repo: repository_fingerprint(root) for repo, root in roots.items()}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(manifest['generated_at'])).total_seconds()
        timely = -300 <= age <= 7 * 86400
    except (KeyError, ValueError, TypeError):
        timely = False
    fresh = bool(manifest) and timely and manifest.get('fingerprints') == fingerprints and manifest.get('revision') == revisions
    all_files, invalid = {}, []
    reports = [('app', 'app-python-coverage.json', False), ('engine', 'engine-python-coverage.json', False), ('app', 'javascript-coverage.json', True)]
    for repo, name, js in reports:
        data = read_json(raw_dir / name)
        if data and repo in roots:
            try:
                files = coverage_files(data, roots[repo], js)
                if sum(row['covered_lines'] for row in files.values()) == 0:
                    raise ValueError('No production statements executed')
                all_files.update({(repo, path): row for path, row in files.items()})
            except (ValueError, KeyError, TypeError) as error:
                invalid.append(f'{name}: {error}')
    debt = read_json(raw_dir / 'debt.json', {})
    baseline = read_json(ROOT / 'quality/baseline.json', {})
    exceptions = active_exceptions({module['id'] for _, module in module_items(catalogs)})
    violations = architecture(roots, ownership)
    tests = {repo: test_results(raw_dir / f'{repo}-tests.xml', root=roots[repo]) for repo in roots}
    tests['app'] += test_results(raw_dir / 'javascript-tests.json', True)
    changes = {repo: changed_lines(root, base if repo == 'app' else None) for repo, root in roots.items()}
    modules = {}
    for repo, module in module_items(catalogs):
        mid = module['id']
        owned = [path for (r, path), owner in ownership.items() if owner == mid and r == repo]
        executable = [path for path in owned if (path.startswith(('backend/', 'src/')) and path.endswith('.py')) or path.startswith('static/js/')]
        missing = [path for path in executable if (repo, path) not in all_files]
        measured = [all_files[(repo, path)] for path in executable if (repo, path) in all_files]
        cov = {'status': 'not_measured'}
        if measured:
            cov = {'status': 'stale' if not fresh else 'invalid' if missing or invalid else 'measured',
                   'lines': percent(sum(row['covered_lines'] for row in measured), sum(row['lines'] for row in measured)),
                   'branches': percent(sum(row['covered_branches'] for row in measured), sum(row['branches'] for row in measured)),
                   'missing_files': missing, 'errors': invalid, 'artifacts': [f'raw/{name}' for r, name, _ in reports if r == repo and (raw_dir / name).exists()]}
        if not executable:
            cov = {'status': 'not_applicable'}
        cases = [row for row in tests[repo] if any(matches(relative_report_path(row['file'], roots[repo]) or '', pattern) for pattern in module['paths']['tests'])]
        expected_tests = {path.relative_to(roots[repo]).as_posix() for pattern in module['paths']['tests'] for path in roots[repo].glob(pattern)}
        missing_tests = sorted(expected_tests - {relative_report_path(row['file'], roots[repo]) for row in cases})
        test_status = 'not_measured' if not cases else 'stale' if not fresh else 'fail' if any(row['failed'] for row in cases) else 'attention' if any(row['skipped'] for row in cases) else 'pass'
        if missing_tests and test_status == 'pass':
            test_status = 'attention'
        slots = ['owner', 'reviewed', 'invariants', 'explanation']
        if module['criticality'] == 'critical':
            slots += ['reference', 'decision']
        if module['docs'].get('operations'):
            slots += ['operations']
        satisfied = sum(bool(module.get(slot) or module['docs'].get(slot)) for slot in slots)
        docs = {'status': 'pass' if satisfied == len(slots) else 'attention', 'satisfied': satisfied, 'required': len(slots), 'slots': slots}
        module_findings = [finding for finding in debt.get('findings', []) if mid in finding['modules']]
        lanes = {}
        for lane, kind in [('duplication', 'clone'), ('dead_code', 'dead_code')]:
            findings = [finding for finding in module_findings if finding['kind'] == kind]
            new = [finding for finding in findings if finding['id'] not in {f['id'] for f in baseline.get('findings', [])}]
            lanes[lane] = {'status': 'not_measured' if not debt else 'stale' if not fresh else 'attention' if new else 'pass', 'count': len(findings), 'new': len(new), 'artifact': 'raw/debt.json'}
        python_inventory = debt.get('analyzed_python_files')
        dead_code = lanes['dead_code']
        dead_code.update(analyzer='Vulture', scope='Python', minimum_confidence=100)
        if python_inventory is None:
            dead_code['status'] = 'not_measured'
        elif not isinstance(python_inventory, list) or any(not isinstance(path, str) for path in python_inventory):
            dead_code['status'] = 'invalid'
        elif not any(f'{repo}:{path}' in python_inventory for path in owned):
            dead_code['status'] = 'not_applicable'
        if dead_code['status'] in {'not_measured', 'invalid', 'not_applicable'}:
            del dead_code['count'], dead_code['new']
        changed = {'status': 'not_measured'}
        if changes[repo] is not None:
            total = covered = 0
            for path in executable:
                data = all_files.get((repo, path), {})
                lines = changes[repo].get(path, set()) & set(data.get('measured_lines', []))
                total += len(lines)
                covered += len(lines & set(data.get('executed_lines', [])))
            changed = {'status': 'stale' if not fresh else 'attention' if missing else 'measured' if total else 'not_applicable', 'lines': percent(covered, total), 'covered': covered, 'total': total, 'target': 90, 'policy': 'advisory'}
        mutation = mutation_evidence(raw_dir / 'engine-mutation.json', roots.get('engine')) if mid == 'engine.result-producer' else {'status': 'not_measured'}
        modules[mid] = dict(criticality=module['criticality'], tests={'status': test_status, 'count': sum(row['count'] for row in cases), 'skipped': sum(row['skipped'] for row in cases), 'missing_files': missing_tests},
                            coverage=cov, mutation=mutation, **lanes, docs=docs,
                            architecture={'status': 'fail' if any(row['module'] == mid for row in violations) else 'pass', 'violations': [row for row in violations if row['module'] == mid]},
                            security={'status': 'not_measured'}, changed_coverage=changed, exceptions=[item for item in exceptions if item['module'] == mid])
    artifact = dict(schema_version=1, revision=revisions, fingerprints=fingerprints, generated_at=datetime.now(timezone.utc).isoformat(),
                    completeness='stale' if manifest and not fresh else 'partial' if any(row[lane]['status'] in {'not_measured', 'invalid'} for row in modules.values() for lane in ('tests', 'coverage', 'mutation', 'security')) else 'complete',
                    checks=manifest.get('checks', []), modules=modules, artifacts=sorted(path.relative_to(ROOT / 'quality').as_posix() for path in raw_dir.rglob('*') if path.is_file() and path.suffix in {'.json', '.xml', '.txt'} and not any(part.startswith('.') for part in path.relative_to(raw_dir).parts)), tools=manifest.get('tool_versions', manifest.get('tools', {})))
    schema_validate(artifact, ROOT / 'quality/latest.schema.json')
    write_json(ROOT / 'quality/latest.json', artifact)
    # Same renderer is used by the portal. The page is a projection, not a database.
    from backend.services.quality_report import render_report
    (ROOT / 'quality/report.md').write_text(render_report(artifact))
    return artifact


JS_FACTS = Path(__file__).resolve().parent / 'quality_js_symbols.mjs'
DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
ROUTE_DECORATORS = {'route', 'get', 'post', 'put', 'patch', 'delete'}
TEMPLATE_TAG = re.compile(r'{%-?\s*(extends|include|import|from)\s+(["\'])(.+?)\2')
TEMPLATE_URL_FOR = re.compile(r'url_for\(\s*(["\'])([\w.]+)\1')
TEMPLATE_PATH = re.compile(r'(["\'])(/[^"\'\s<>{}]+)\1')
URL_PLACEHOLDER = '{}'
CODE_LINK_KINDS = {'imports', 'loads', 'uses', 'calls', 'requests', 'links', 'renders', 'extends', 'includes'}


def javascript_facts(paths):
    """Parse browser scripts with espree, the parser ESLint uses: symbols, shared globals, references, URLs and requests."""
    if not paths:
        return {}
    result = subprocess.run(['node', str(JS_FACTS)], input=json.dumps([str(path) for path in paths]), capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f'JavaScript parsing failed: {result.stderr.strip()}')
    return json.loads(result.stdout)


def flask_routes(fid, tree):
    """The routes a Python file registers on a Flask app or blueprint it creates, each pointing at its view function."""
    owners = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            constructor = getattr(node.value.func, 'id', getattr(node.value.func, 'attr', None))
            if constructor in {'Flask', 'Blueprint'}:
                name = node.value.args[0].value if constructor == 'Blueprint' and node.value.args and isinstance(node.value.args[0], ast.Constant) else None
                owners.update({target.id: name for target in node.targets if isinstance(target, ast.Name)})
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in ROUTE_DECORATORS
                    and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id in owners
                    and decorator.args and isinstance(decorator.args[0], ast.Constant)):
                continue
            keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
            methods = ['GET'] if decorator.func.attr == 'route' else [decorator.func.attr.upper()]
            if isinstance(keywords.get('methods'), (ast.List, ast.Tuple)):
                methods = [item.value.upper() for item in keywords['methods'].elts if isinstance(item, ast.Constant)]
            endpoint = keywords['endpoint'].value if isinstance(keywords.get('endpoint'), ast.Constant) else node.name
            blueprint = owners[decorator.func.value.id]
            yield dict(pattern=decorator.args[0].value, methods=sorted(methods), endpoint=f'{blueprint}.{endpoint}' if blueprint else endpoint,
                       symbol=f'{fid}:{node.name}@{node.lineno}', file=fid, line=node.lineno)


def route_regex(pattern):
    """A Flask URL rule as a regular expression: ``<path:name>`` spans segments, every other converter is one segment."""
    regex = re.sub(r'<path:[^>]+>', '.+', re.escape(pattern))
    return re.compile('^' + re.sub(r'<[^>]+>', '[^/]+', regex) + '$')


def match_route(url, routes):
    """The route a URL string reaches, or None. Runtime parts match any segment; a string ending in ``/`` expects one more."""
    path = re.split(r'[?#]', url, maxsplit=1)[0].replace(URL_PLACEHOLDER, 'x')
    candidates = [path] + ([path + 'x'] if path.endswith('/') else [])
    found = [route for route in routes if any(route['regex'].match(candidate) for candidate in candidates)]
    # Flask prefers the rule with the most fixed text, as `/docs/assets/<path>` over `/docs/<path>`.
    return max(found, key=lambda route: len(re.sub(r'<[^>]+>', '', route['pattern'])), default=None)


def unique_rows(rows):
    """Rows without repeats, in file and line order. A nested function's call is seen from its enclosing function too."""
    return sorted({json.dumps(row, sort_keys=True): row for row in rows}.values(), key=lambda row: (row['file'], row['line'], json.dumps(row, sort_keys=True)))


def build_map(roots, catalogs, ownership):
    nodes, edges, file_ids, symbols = [], [], {}, {}
    def edge(source, target, kind, provenance='declared', **extra):
        edges.append(dict(source=source, target=target, kind=kind, provenance=provenance, **extra))
    for repo, module in module_items(catalogs):
        mid = module['id']
        nodes.append(dict(id=mid, kind='module', repository=repo, title=module['title']))
        for dependency in module.get('dependencies', []):
            edge(mid, dependency, 'depends-on')
        for kind, paths in module['docs'].items():
            for path in paths:
                did = f'{repo}:{path}'
                nodes.append(dict(id=did, kind='document', path=path))
                edge(mid, did, 'documented-by', category=kind)
        for pattern in module['paths']['tests']:
            for path in roots[repo].glob(pattern):
                tid = f'{repo}:{path.relative_to(roots[repo]).as_posix()}'
                nodes.append(dict(id=tid, kind='test', path=path.relative_to(roots[repo]).as_posix()))
                edge(mid, tid, 'tested-by')
    texts = {(repo, path): (roots[repo] / path).read_text() for repo, path in ownership}
    for (repo, path), mid in ownership.items():
        fid = f'{repo}:{path}'
        nodes.append(dict(id=fid, kind='file', path=path, module=mid, lines=len(texts[(repo, path)].splitlines())))
        edge(mid, fid, 'contains', 'static-exact')
        if path.endswith('.py'):
            file_ids[(repo, python_module(path))] = fid
    python, scripts, top = {}, {}, {}
    javascript = javascript_facts([roots[repo] / path for repo, path in ownership if path.endswith('.js')])
    # Route references, resolved once every route is known: (source, file, URL or endpoint, line, link kind).
    routes, urls, endpoints, rendered, unmatched, dynamic = [], [], [], [], [], []
    def line_of(text, offset):
        return text.count('\n', 0, offset) + 1
    for (repo, path), mid in ownership.items():
        fid = f'{repo}:{path}'
        text = texts[(repo, path)]
        if path.endswith('.py'):
            tree = ast.parse(text)
            routes.extend(flask_routes(fid, tree))
            local = {}
            for node in ast.walk(tree):
                if isinstance(node, DEFINITIONS):
                    sid = f'{fid}:{node.name}@{node.lineno}'
                    local.setdefault(node.name, []).append(sid)
                    nodes.append(dict(id=sid, kind='symbol', name=node.name, path=path, line=node.lineno, module=mid, provenance='static-exact'))
                    edge(fid, sid, 'contains', 'static-exact')
                    symbols[sid] = node
            top[fid] = {node.name: f'{fid}:{node.name}@{node.lineno}' for node in tree.body if isinstance(node, DEFINITIONS)}
            python[fid] = (repo, path, tree, local)
        elif path.endswith('.js'):
            facts = javascript[str(roots[repo] / path)]
            sids = [f"{fid}:{symbol['name']}@{symbol['line']}" for symbol in facts['symbols']]
            for symbol, sid in zip(facts['symbols'], sids):
                nodes.append(dict(id=sid, kind='symbol', name=symbol['name'], path=path, line=symbol['line'], module=mid, provenance='static-exact'))
                edge(fid, sid, 'contains', 'static-exact')
            # A name read inside a function or class is read by it; outside any, by the file.
            facts['sources'] = [fid if reference['symbol'] is None else sids[reference['symbol']] for reference in facts['references']]
            for item in facts['links']:
                edge(fid if item['source'] is None else sids[item['source']], sids[item['target']], item['kind'], 'static-exact', line=item['line'])
            scripts[fid] = facts
            requested = {item['url'] for item in facts['requests'] if item['url']}
            for item in facts['requests']:
                if not item['url']:
                    dynamic.append(dict(file=fid, line=item['line'], kind='request', expression=item['expression']))
            for item in facts['strings']:
                urls.append((fid, fid, item['value'], item['line'], item['value'] in requested))
        elif path.endswith('.html'):
            for match in TEMPLATE_TAG.finditer(text):
                rendered.append((fid, fid, match[3], line_of(text, match.start()), 'extends' if match[1] == 'extends' else 'includes'))
            for match in TEMPLATE_URL_FOR.finditer(text):
                if match[2] != 'static':
                    endpoints.append((fid, fid, match[2], line_of(text, match.start())))
            for match in re.finditer(r'url_for\(\s*([A-Za-z_]\w*)', text):
                dynamic.append(dict(file=fid, line=line_of(text, match.start()), kind='url_for', expression=match[1]))
            for match in TEMPLATE_PATH.finditer(text):
                urls.append((fid, fid, match[2], line_of(text, match.start()), False))
            for order, script in enumerate(re.findall(r'<script\b[^>]*\bsrc\s*=\s*(["\'])(.*?)\1', text, re.S)):
                src = script[1]
                match = re.search(r'filename=["\']([^"\']+)', src)
                # Jinja quote nesting is resolved separately below.
                target = match[1] if match else src.removeprefix('/static/')
                if (repo, 'static/' + target) in ownership:
                    edge(fid, f'{repo}:static/{target}', 'loads', 'static-exact', order=order)
            for order, target in enumerate(re.findall(r'<script[^>]*filename=["\'](js/[^"\']+)', text)):
                if (repo, 'static/' + target) in ownership:
                    edge(fid, f'{repo}:static/{target}', 'loads', 'static-exact', order=order)
    imports = {fid: list(import_bindings(tree, import_context(path))) for fid, (repo, path, tree, _) in python.items()}
    # A package re-exports what its __init__ imports, as `results:write_bundle` does.
    exports = {fid: {**{name: top[target][attribute] for name, module, attribute, _ in imports[fid]
                        if attribute and (target := file_ids.get((python[fid][0], module))) and attribute in top[target]}, **top[fid]}
               for fid in python}
    for fid, (repo, path, tree, local) in python.items():
        # `from package import submodule` reaches the submodule, not the package's __init__.
        bound_modules, bound_symbols = {}, {}
        for name, module, attribute, line in imports[fid]:
            submodule = file_ids.get((repo, f'{module}.{attribute}')) if attribute else None
            target = submodule or file_ids.get((repo, module))
            if not target:
                continue
            edge(fid, target, 'imports', 'static-exact', line=line)
            if submodule or (name and not attribute):
                bound_modules[name] = target
            elif attribute in exports[target]:
                bound_symbols[name] = exports[target][attribute]
                edge(fid, bound_symbols[name], 'uses', 'static-exact', line=line)
        for sid in [key for values in local.values() for key in values]:
            for call in ast.walk(symbols[sid]):
                if not isinstance(call, ast.Call):
                    continue
                flask_helper = getattr(call.func, 'id', getattr(call.func, 'attr', None))
                if flask_helper in {'render_template', 'url_for'} and call.args:
                    argument = call.args[0]
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        if flask_helper == 'render_template':
                            rendered.append((sid, fid, argument.value, call.lineno, 'renders'))
                        elif argument.value != 'static':
                            endpoints.append((sid, fid, argument.value, call.lineno))
                    else:
                        dynamic.append(dict(file=fid, line=call.lineno, kind=flask_helper, expression=ast.unparse(argument)))
                if isinstance(call.func, ast.Name):
                    targets = local.get(call.func.id) or ([bound_symbols[call.func.id]] if call.func.id in bound_symbols else [])
                elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in bound_modules:
                    target = exports.get(bound_modules[call.func.value.id], {}).get(call.func.attr)
                    targets = [target] if target else []
                else:
                    targets = []
                for target in targets:
                    edge(sid, target, 'calls', 'static-heuristic', line=call.lineno)
    # Browser scripts share one global scope: a name a script reads but does not declare is the export of the one
    # script that shares it. A name shared by several scripts is ambiguous, so it is reported instead of linked.
    shared = {}
    for fid, facts in scripts.items():
        for name, line in facts['globals'].items():
            shared.setdefault(name, []).append(f'{fid}:{name}@{line}')
    for fid, facts in scripts.items():
        for reference, source in zip(facts['references'], facts['sources']):
            targets = shared.get(reference['name'], [])
            if len(targets) == 1 and reference['name'] not in facts['globals']:
                edge(source, targets[0], 'uses', 'static-exact', line=reference['line'])
    # Requests and links reach a view function through its URL rule or its endpoint name. Asking an API route, or
    # sending a request, uses the view's code. Any other reference to a page is a link, recorded but drawing no
    # module arrow: following a link does not use the page's code.
    for route in routes:
        route['regex'] = route_regex(route['pattern'])
    by_endpoint = {route['endpoint']: route for route in routes}
    def route_kind(route, request=False):
        return 'requests' if request or route['pattern'].startswith('/api/') else 'links'
    for source, fid, url, line, request in urls:
        route = match_route(url, routes)
        if route:
            edge(source, route['symbol'], route_kind(route, request), 'static-heuristic', line=line)
        elif request or url.startswith('/api/'):
            unmatched.append(dict(file=fid, line=line, kind='url', reference=url))
    for source, fid, endpoint, line in endpoints:
        if endpoint in by_endpoint:
            edge(source, by_endpoint[endpoint]['symbol'], route_kind(by_endpoint[endpoint]), 'static-exact', line=line)
        else:
            unmatched.append(dict(file=fid, line=line, kind='endpoint', reference=endpoint))
    for source, fid, name, line, kind in rendered:
        repo = fid.split(':', 1)[0]
        if (repo, f'templates/{name}') in ownership:
            edge(source, f'{repo}:templates/{name}', kind, 'static-exact', line=line)
        elif not (roots[repo] / 'templates' / name).is_file():
            unmatched.append(dict(file=fid, line=line, kind='template', reference=name))
        # A template that exists but is no code file, as llms.txt, has no node to link to.
    for repo, catalog in catalogs.items():
        for contract in catalog.get('contracts', []):
            cid = 'contract.' + contract['id']
            nodes.append(dict(id=cid, kind='contract', title=contract.get('title', cid)))
            for mid in contract['producers']:
                edge(mid, cid, 'produces')
            for mid in contract['consumers']:
                edge(cid, mid, 'consumes')
    graph = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                 limitations=['Python import syntax is exact; runtime resolution can differ.',
                              'Python calls resolve through local definitions and imports only; calls through objects, attributes of instances and dynamic dispatch are missing.',
                              'JavaScript is parsed with espree. A global a script reads is linked to the one script that shares it; whether both load on the same page is not checked.',
                              'JavaScript calls resolve through the names in scope only; calls through objects, such as this.render(), and methods of objects passed around are missing.',
                              'HTTP requests and page links reach a Flask route through its URL text or url_for endpoint. A URL built at runtime is listed as a blind spot, not linked.',
                              'Shared database tables, external services and the data a view passes to its template are not links.'],
                 routes=[{key: value for key, value in route.items() if key != 'regex'} for route in routes],
                 blind_spots=dict(unmatched=unique_rows(unmatched), dynamic=unique_rows(dynamic),
                                  shared_names=[dict(name=name, symbols=sorted(sids)) for name, sids in sorted(shared.items()) if len(sids) > 1]),
                 nodes=list({node['id']: node for node in nodes}.values()), edges=list({json.dumps(item, sort_keys=True): item for item in edges}.values()))
    write_json(ROOT / 'quality/quality-map.json', graph)
    write_json(ROOT / 'quality/code-map.json', code_map(graph, catalogs))
    return graph


def code_map(graph, catalogs):
    """Module, file and boundary view of the map: what the code-quality dashboard draws."""
    nodes = {node['id']: node for node in graph['nodes']}
    def file_of(node_id):
        return node_id if nodes[node_id]['kind'] == 'file' else node_id.rsplit(':', 1)[0]
    links, used_by, reexports, route_users, symbol_links = {}, {}, {}, {}, {}
    for item in graph['edges']:
        source, target = nodes.get(item['source']), nodes.get(item['target'])
        if item['kind'] not in CODE_LINK_KINDS or not source or not target or 'module' not in source or 'module' not in target:
            continue
        if item['kind'] == 'uses' and source['kind'] == 'file':
            reexports.setdefault(source['id'], []).append(target['id'])
        key = (file_of(source['id']), file_of(target['id']), item['kind'])
        if key[0] != key[1]:
            links[key] = links.get(key, 0) + 1
        # The function view: every link with a function or class at one end, including links inside one file.
        if 'symbol' in (source['kind'], target['kind']) and source['id'] != target['id']:
            key = (source['id'], target['id'], item['kind'])
            symbol_links[key] = symbol_links.get(key, 0) + 1
        if item['kind'] in {'requests', 'links'}:
            route_users.setdefault((target['id'], item['kind']), set()).add(file_of(source['id']))
        # Following a link to a page does not use its code, so links are no part of a module's interface.
        if source['module'] != target['module'] and target['kind'] == 'symbol' and item['kind'] != 'links':
            used_by.setdefault(target['id'], set()).add(source['module'])
    symbols = {}
    for node in graph['nodes']:
        if node['kind'] == 'symbol':
            symbols.setdefault(file_of(node['id']), []).append(node)
    modules, interface = [], {}
    for repo, module in module_items(catalogs):
        declared = []
        for entry in module['entrypoints']:
            name, _, symbol = entry.partition(':')
            files = [fid for fid in symbols.keys() | reexports.keys() if fid.startswith(f'{repo}:') and python_module(fid.split(':', 1)[1]) == name]
            match = next((node['id'] for fid in files for node in symbols.get(fid, []) if node['name'] == symbol.split('.')[0]), None)
            match = match or next((sid for fid in files for sid in reexports.get(fid, []) if nodes[sid]['name'] == symbol.split('.')[0]), None)
            declared.append(dict(entry=entry, symbol=match))
        modules.append(dict(id=module['id'], repository=repo, title=module['title'], criticality=module['criticality'],
                            responsibility=module['responsibility'], owner=module['owner'], reviewed=module['reviewed'],
                            invariants=module['invariants'], entrypoints=declared, dependencies=module.get('dependencies', []),
                            tests=module['paths']['tests'], docs=module['docs']))
        interface[module['id']] = []
    for sid, users in sorted(used_by.items()):
        node = nodes[sid]
        interface[node['module']].append(dict(id=sid, name=node['name'], file=file_of(sid), line=node['line'], used_by=sorted(users)))
    contracts = [dict(id=contract['id'], title=contract.get('title', contract['id']), producers=contract['producers'], consumers=contract['consumers'])
                 for catalog in catalogs.values() for contract in catalog.get('contracts', [])]
    files = [dict(id=node['id'], module=node['module'], lines=node.get('lines', 0), symbols=len(symbols.get(node['id'], [])))
             for node in graph['nodes'] if node['kind'] == 'file']
    routes = [dict(route, requested_by=sorted(route_users.get((route['symbol'], 'requests'), ())),
                   linked_by=sorted(route_users.get((route['symbol'], 'links'), ())))
              for route in sorted(graph.get('routes', []), key=lambda route: (route['pattern'], route['endpoint']))]
    return dict(schema_version=1, generated_at=graph['generated_at'], limitations=graph['limitations'], modules=modules, contracts=contracts,
                files=sorted(files, key=lambda row: row['id']), interface=interface, routes=routes,
                symbols=sorted((dict(id=node['id'], name=node['name'], file=file_of(node['id']), line=node['line'])
                                for node in graph['nodes'] if node['kind'] == 'symbol'), key=lambda row: (row['file'], row['line'], row['name'])),
                symbol_links=[dict(source=source, target=target, kind=kind, count=count) for (source, target, kind), count in sorted(symbol_links.items())],
                blind_spots=graph.get('blind_spots', dict(unmatched=[], dynamic=[], shared_names=[])),
                links=[dict(source=source, target=target, kind=kind, count=count) for (source, target, kind), count in sorted(links.items())])


def context(module_id, roots, catalogs, ownership):
    repo, module = next(((repo, module) for repo, module in module_items(catalogs) if module['id'] == module_id), (None, None))
    if module is None:
        raise ValueError(f'Unknown module: {module_id}')
    graph = build_map(roots, catalogs, ownership)
    owned = {f'{repo}:{path}' for (r, path), owner in ownership.items() if r == repo and owner == module_id}
    neighbors = sorted({edge['target'] for edge in graph['edges'] if edge['source'] in owned and edge['kind'] == 'imports'})
    return '\n'.join([f"Module: {module_id} ({module['criticality']})", f"Owner: {module['owner']}", f"Responsibility: {module['responsibility']}",
                       'Invariants: ' + '; '.join(module['invariants']), 'Entrypoints: ' + ', '.join(module['entrypoints']),
                       'Contracts: ' + json.dumps(module.get('contracts', {})), 'Dependencies: ' + ', '.join(neighbors),
                       'Tests: ' + ', '.join(module['paths']['tests']), 'Docs: ' + ', '.join(path for paths in module['docs'].values() for path in paths),
                       'Fast: make quality-fast', 'Full: make quality', 'Failures and exceptions: quality/latest.json and quality/exceptions.json'])


def occurrence_findings(findings):
    """Deduplicate repeated analyzer output without forgiving extra copies.

    A content/file fingerprint remains stable when source lines shift. Number
    distinct physical occurrences within each fingerprint so another identical
    clone in the same files still adds a finding beyond the reviewed baseline.
    """
    groups = {}
    for finding in findings:
        fingerprint = finding['id']
        location = json.dumps(sorted(finding['locations'], key=lambda item: json.dumps(item, sort_keys=True)), sort_keys=True)
        groups.setdefault(fingerprint, {})[location] = finding
    result = []
    for fingerprint, occurrences in sorted(groups.items()):
        for index, (_, finding) in enumerate(sorted(occurrences.items()), 1):
            result.append({**finding, 'fingerprint': fingerprint, 'occurrence': index,
                           'id': hashlib.sha256(f'{fingerprint}:{index}'.encode()).hexdigest()})
    return sorted(result, key=lambda finding: finding['id'])


def debt(roots, catalogs, ownership, write_baseline=False):
    raw_dir = ROOT / 'quality/raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    exclusions = read_json(ROOT / 'quality/exclusions.json')['duplication']
    files = [(repo, path) for repo, path in ownership if Path(path).suffix in {'.py', '.js', '.mjs', '.cjs', '.css', '.html', '.sh', '.yml', '.yaml'} and not excluded(path, exclusions)]
    command = [str(ROOT / 'node_modules/.bin/jscpd'), '--min-lines', '10', '--min-tokens', '70', '--reporters', 'json', '--output', str(raw_dir / 'jscpd'), '--silent']
    subprocess.run(command + [str(roots[repo] / path) for repo, path in files], check=True, cwd=ROOT)
    findings = []
    def locate(name):
        resolved = (ROOT / name).resolve()
        for repo, root in sorted(roots.items(), key=lambda item: len(str(item[1])), reverse=True):
            try:
                path = resolved.relative_to(root).as_posix()
                return repo, path, ownership.get((repo, path))
            except ValueError:
                pass
        raise ValueError(f'Analyzer returned unknown file {name}')
    for clone in read_json(raw_dir / 'jscpd/jscpd-report.json')['duplicates']:
        locations = [locate(clone[side]['name']) for side in ('firstFile', 'secondFile')]
        fragment = clone.get('fragment', '')
        if not fragment:
            repo, path, _ = locations[0]
            lines = (roots[repo] / path).read_text().splitlines()
            fragment = '\n'.join(lines[clone['firstFile']['start'] - 1:clone['firstFile']['end']])
        identity = json.dumps(sorted(f'{repo}:{path}' for repo, path, _ in locations)) + re.sub(r'\s+', ' ', fragment)
        physical_locations = [dict(file=f'{repo}:{path}', start=clone[side]['start'], end=clone[side]['end'],
                                   start_column=clone[side].get('startLoc', {}).get('column'), end_column=clone[side].get('endLoc', {}).get('column'))
                              for side, (repo, path, _) in zip(('firstFile', 'secondFile'), locations)]
        findings.append(dict(id=hashlib.sha256(identity.encode()).hexdigest(), kind='clone', modules=sorted({mid for _, _, mid in locations if mid}), files=[f'{repo}:{path}' for repo, path, _ in locations], lines=clone.get('lines'), fragment=fragment, locations=physical_locations))
    python_files = [str(roots[repo] / path) for repo, path in files if path.endswith('.py')]
    result = subprocess.run([sys.executable, '-m', 'vulture', *python_files, '--min-confidence', '100'], capture_output=True, text=True)
    (raw_dir / 'vulture.txt').write_text(result.stdout + result.stderr)
    if result.returncode not in (0, 3):
        raise ValueError(f'Vulture failed: {result.stdout}{result.stderr}')
    for line in result.stdout.splitlines():
        match = re.match(r'(.+?):(\d+): (.+)', line)
        if not match:
            raise ValueError(f'Unrecognized Vulture finding: {line}')
        repo, path, mid = locate(match[1])
        source_line = (roots[repo] / path).read_text().splitlines()[int(match[2]) - 1].strip()
        identity = f'{repo}:{path}:{match[3]}:{source_line}'
        findings.append(dict(id=hashlib.sha256(identity.encode()).hexdigest(), kind='dead_code', modules=[mid], files=[f'{repo}:{path}'], line=int(match[2]), message=match[3], locations=[dict(file=f'{repo}:{path}', start=int(match[2]), end=int(match[2]))]))
    findings = occurrence_findings(findings)
    evidence = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(), findings=findings,
                    analyzed_python_files=sorted(f'{repo}:{path}' for repo, path in files if path.endswith('.py')))
    write_json(raw_dir / 'debt.json', evidence)
    baseline_path = ROOT / 'quality/baseline.json'
    baseline = read_json(baseline_path, {})
    if write_baseline:
        write_json(baseline_path, evidence)
        return f'Wrote reviewable baseline: {len(findings)} findings'
    exceptions = active_exceptions({module['id'] for _, module in module_items(catalogs)})
    allowed = {finding['id'] for finding in baseline.get('findings', [])}
    allowed.update(item['finding'] for item in exceptions
                   if any(finding['id'] == item['finding'] and item['module'] in finding['modules'] for finding in findings))
    new = [finding for finding in findings if finding['id'] not in allowed]
    if new:
        raise ValueError(f'{len(new)} new structural findings. Inspect quality/raw/debt.json; fix them or record an expiring exception. Baseline updates require review.')
    if not baseline:
        raise ValueError('No reviewed structural baseline. Run debt --write-baseline and review quality/baseline.json.')
    return f'No new structural debt ({len(findings)} existing findings)'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'coverage', 'report', 'map', 'context', 'impact', 'symbol', 'debt'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--engine-dir', type=Path, help='Engine checkout (default: ENGINE_DIR, engine/ or ../engine)')
    parser.add_argument('--base', help='App git revision for advisory changed-line coverage')
    parser.add_argument('--depth', type=int, choices=[1, 2], default=1)
    parser.add_argument('--write-baseline', action='store_true')
    args = parser.parse_args()
    try:
        roots, catalogs, ownership = load_catalogs(args.engine_dir or engine_dir())
        if args.command == 'check':
            print(check(roots, catalogs, ownership))
        elif args.command == 'coverage':
            print(coverage_sanity(roots, ownership))
        elif args.command == 'report':
            result = report(roots, catalogs, ownership, args.base)
            build_map(roots, catalogs, ownership)
            print(f"quality/latest.json and quality/report.md: {result['completeness']}")
        elif args.command == 'context':
            print(context(args.target, roots, catalogs, ownership))
        elif args.command == 'debt':
            print(debt(roots, catalogs, ownership, args.write_baseline))
        else:
            graph = build_map(roots, catalogs, ownership)
            if args.command in {'symbol', 'impact'}:
                if not args.target:
                    raise ValueError('Supply a module, path, or symbol search term')
                selected = {node['id'] for node in graph['nodes'] if args.target.lower() in node['id'].lower()}
                for _ in range(args.depth):
                    selected |= {edge[side] for edge in graph['edges'] if edge['source'] in selected or edge['target'] in selected for side in ('source', 'target')}
                graph['nodes'] = [node for node in graph['nodes'] if node['id'] in selected]
                graph['edges'] = [edge for edge in graph['edges'] if edge['source'] in selected and edge['target'] in selected]
                print(json.dumps(graph, indent=2))
            else:
                print(f"quality/quality-map.json: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Quality check failed: {error}\n')


if __name__ == '__main__':
    main()
