"""Acceptance tests for evidence integrity, ownership and architecture policies."""
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from scripts import quality


def test_globs_include_direct_and_nested_files():
    assert quality.matches('backend/a.py', 'backend/**/*.py')
    assert quality.matches('backend/importing/a.py', 'backend/**/*.py')
    assert not quality.matches('static/a.js', 'backend/**/*.py')


def test_commonjs_scripts_are_in_the_ownership_inventory(tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/check.cjs').write_text('module.exports = {};\n')
    assert quality.source_files(tmp_path, {'source_roots': ['scripts']}, []) == ['scripts/check.cjs']


def test_clone_budget_counts_extra_copies_but_not_repeated_analyzer_output():
    original = {'id': 'same-content-and-file-pair', 'kind': 'clone', 'locations': [
        {'file': 'app:a.js', 'start': 10, 'end': 20}, {'file': 'app:b.js', 'start': 30, 'end': 40}]}
    repeated = {**original, 'locations': list(reversed(original['locations']))}
    baseline = quality.occurrence_findings([original, repeated])
    assert len(baseline) == 1
    added = {**original, 'locations': [original['locations'][0], {'file': 'app:b.js', 'start': 70, 'end': 80}]}
    current = quality.occurrence_findings([original, repeated, added])
    assert len(current) == 2
    assert len({item['id'] for item in current} - {item['id'] for item in baseline}) == 1


def test_clone_identity_survives_line_movement_without_allowing_new_content():
    original = {'id': 'first-content', 'kind': 'clone', 'locations': [
        {'file': 'app:a.js', 'start': 10, 'end': 20}, {'file': 'app:a.js', 'start': 30, 'end': 40}]}
    shifted = {**original, 'locations': [{**item, 'start': item['start'] + 9, 'end': item['end'] + 9} for item in original['locations']]}
    assert quality.occurrence_findings([original])[0]['id'] == quality.occurrence_findings([shifted])[0]['id']
    changed = {**shifted, 'id': 'different-content'}
    assert quality.occurrence_findings([original])[0]['id'] != quality.occurrence_findings([changed])[0]['id']


def test_source_ownership_rejects_missing_or_duplicate_owner(tmp_path, monkeypatch):
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/a.py').write_text('answer = 42\n')
    (tmp_path / 'quality/exclusions.json').write_text('{"source": []}')
    catalog = {'source_roots': ['src'], 'modules': []}
    path = tmp_path / 'quality/modules.yml'
    path.write_text(json.dumps(catalog))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'schema_validate', lambda *args: None)
    with pytest.raises(ValueError, match='exactly one owner'):
        quality.load_catalogs()
    catalog['modules'] = [{'id': name, 'paths': {'source': ['src/**']}} for name in ['first', 'second']]
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='exactly one owner'):
        quality.load_catalogs()


def test_python_coverage_requires_branch_measurement(tmp_path):
    with pytest.raises(ValueError, match='branch coverage'):
        quality.coverage_files({'meta': {'branch_coverage': False}}, tmp_path)


def test_javascript_coverage_counts_never_executed_statements(tmp_path):
    data = {'static/js/a.js': {'statementMap': {'0': {'start': {'line': 1}}, '1': {'start': {'line': 2}}}, 's': {'0': 1, '1': 0}, 'b': {'0': [1, 0]}}}
    result = quality.coverage_files(data, tmp_path, True)['static/js/a.js']
    assert result['lines'] == 2
    assert result['covered_lines'] == 1
    assert result['branches'] == 2
    assert result['covered_branches'] == 1


def test_architecture_rejects_hidden_engine_import(tmp_path):
    (tmp_path / 'app.py').write_text('def run():\n    from transport_matcher import match\n')
    findings = quality.architecture({'app': tmp_path}, {('app', 'app.py'): 'app.query-api'})
    assert findings and findings[0]['line'] == 2


def test_core_architecture_resolves_relative_imports(tmp_path):
    file = tmp_path / 'src/transport_matcher/core/matching.py'
    file.parent.mkdir(parents=True)
    file.write_text('from ..adapters import gtfs\n')
    assert quality.architecture({'engine': tmp_path}, {('engine', 'src/transport_matcher/core/matching.py'): 'engine.core-matching'})


def test_expired_exceptions_fail(tmp_path, monkeypatch):
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/exceptions.json').write_text(json.dumps([{'module': 'test', 'finding': 'a', 'owner': 'maintainer', 'reason': 'temporary', 'expires': '2000-01-01'}]))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='expired'):
        quality.active_exceptions({'test'})


def test_fingerprint_changes_for_dirty_source_but_not_generated_output(tmp_path):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / 'source.py').write_text('answer = 41\n')
    before = quality.repository_fingerprint(tmp_path)
    (tmp_path / 'source.py').write_text('answer = 42\n')
    after = quality.repository_fingerprint(tmp_path)
    assert after != before
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/latest.json').write_text('{}')
    assert quality.repository_fingerprint(tmp_path) == after


def test_report_never_treats_missing_file_as_covered(tmp_path, monkeypatch):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    schema = Path(quality.ROOT / 'quality/latest.schema.json').read_text()
    (tmp_path / 'quality/latest.schema.json').write_text(schema)
    (tmp_path / 'a.py').write_text('pass\n')
    module = dict(id='app.test', criticality='high', owner='test', reviewed='2026-09-22', invariants=['Invariant'], docs={'explanation':['README.md']}, paths={'tests':[]})
    coverage = {'meta': {'branch_coverage': True}, 'files': {'backend/a.py': {'summary': {'num_statements': 1, 'covered_lines': 1, 'num_branches': 2, 'covered_branches': 1}, 'executed_lines': [1], 'missing_lines': []}}}
    (raw / 'app-python-coverage.json').write_text(json.dumps(coverage))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'architecture', lambda *args: [])
    monkeypatch.setattr(quality, 'revision', lambda *args: 'sha')
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda *args: 'fingerprint')
    (raw / 'checks.json').write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'revision': {'app':'sha','engine':'sha'}, 'fingerprints': {'app':'fingerprint'}, 'checks': []}))
    result = quality.report({'app':tmp_path}, {'app':{'modules':[module]}}, {('app','backend/a.py'):'app.test', ('app','backend/untested.py'):'app.test'})
    cov = result['modules']['app.test']['coverage']
    assert cov['status'] == 'invalid'
    assert cov['missing_files'] == ['backend/untested.py']
    assert result['modules']['app.test']['tests']['status'] == 'not_measured'


def test_junit_skipped_scenarios_are_not_a_pass(tmp_path):
    path = tmp_path / 'tests.xml'
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_snapshot"><skipped/></testcase><testcase classname="tests.test_snapshot"><failure/></testcase></testsuite></testsuites>')
    rows = quality.test_results(path)
    assert rows[0]['skipped'] == 1
    assert rows[1]['failed'] is True


@pytest.mark.parametrize('inventory,python_status,javascript_status', [
    (['app:backend/app.py'], 'pass', 'not_applicable'),
    (None, 'not_measured', 'not_measured'),
    ({'app:backend/app.py': True}, 'invalid', 'invalid'),
])
def test_dead_code_results_require_recorded_python_analyzer_inputs(tmp_path, monkeypatch, inventory, python_status, javascript_status):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    (tmp_path / 'quality/latest.schema.json').write_text((quality.ROOT / 'quality/latest.schema.json').read_text())
    debt = {'schema_version': 1, 'findings': []}
    if inventory is not None:
        debt['analyzed_python_files'] = inventory
    (raw / 'debt.json').write_text(json.dumps(debt))
    (raw / 'checks.json').write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(),
        'revision': {'app': 'sha', 'engine': 'sha'}, 'fingerprints': {'app': 'fingerprint'}, 'checks': []}))
    modules = [dict(id=mid, criticality='high', owner='test', reviewed='2026-09-22', invariants=['Invariant'],
                    docs={'explanation': ['README.md']}, paths={'tests': []}) for mid in ('app.python', 'app.javascript')]
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'architecture', lambda *args: [])
    monkeypatch.setattr(quality, 'revision', lambda *args: 'sha')
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda *args: 'fingerprint')
    result = quality.report({'app': tmp_path}, {'app': {'modules': modules}}, {
        ('app', 'backend/app.py'): 'app.python', ('app', 'static/js/review.js'): 'app.javascript'})
    for module, status in [('app.python', python_status), ('app.javascript', javascript_status)]:
        lane = result['modules'][module]['dead_code']
        assert lane['status'] == status
        assert lane['analyzer'] == 'Vulture'
        assert lane['scope'] == 'Python'
        assert ('count' in lane) == (status == 'pass')
    assert '| Python dead code |' in (tmp_path / 'quality/report.md').read_text()


def test_junit_class_failures_belong_to_the_test_module(tmp_path):
    path = tmp_path / 'tests.xml'
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_validators.TestPagination" name="test_invalid"><failure/></testcase></testsuite></testsuites>')
    row = quality.test_results(path, root=tmp_path)[0]
    assert row['file'] == 'tests/test_validators.py'
    assert row['failed'] is True


def test_junit_prefers_existing_module_prefix_over_class_name(tmp_path):
    (tmp_path / 'scenarios').mkdir()
    (tmp_path / 'scenarios/contract.py').write_text('')
    assert quality.testcase_file({'classname': 'scenarios.contract.TestBundle.Nested'}, tmp_path) == 'scenarios/contract.py'
    assert quality.testcase_file({'classname': 'ignored.Class', 'file': 'explicit.py'}, tmp_path) == 'explicit.py'


def test_isolated_contract_results_replace_matching_skips_but_keep_failures(tmp_path):
    app = tmp_path / 'app.xml'
    contract = tmp_path / 'contract.xml'
    app.write_text('''<testsuites><testsuite>
        <testcase classname="tests.test_contract" name="test_bundle[gtfs]"><skipped/></testcase>
        <testcase classname="tests.test_contract" name="test_bundle[swiss]"><failure/></testcase>
        <testcase classname="tests.test_contract" name="test_bundle[unrun]"><skipped/></testcase>
        <testcase classname="tests.test_contract" name="test_bundle[regressed]"/>
        </testsuite></testsuites>''')
    contract.write_text('''<testsuites><testsuite>
        <testcase classname="tests.test_contract" name="test_bundle[gtfs]"/>
        <testcase classname="tests.test_contract" name="test_bundle[swiss]"/>
        <testcase classname="tests.test_contract" name="test_bundle[regressed]"><failure/></testcase>
        </testsuite></testsuites>''')
    merged = quality.merge_test_results(quality.test_results(app), quality.test_results(contract), tmp_path)
    assert len(merged) == 4
    by_name = {row['test_id'].split('::')[1]: row for row in merged}
    assert not by_name['test_bundle[gtfs]']['skipped']
    assert by_name['test_bundle[swiss]']['failed']
    assert by_name['test_bundle[regressed]']['failed']
    assert by_name['test_bundle[unrun]']['skipped']


@pytest.mark.parametrize('content', ['not JSON', 'null', '[]', '{}', '{"schema_version": 1, "tests_sha256": []}'])
def test_malformed_optional_mutation_evidence_is_invalid_without_breaking_report(tmp_path, content):
    artifact = tmp_path / 'mutation.json'
    artifact.write_text(content)
    assert quality.mutation_evidence(artifact, tmp_path)['status'] == 'invalid'


def test_mutation_evidence_is_measured_only_for_matching_sources_and_valid_totals(tmp_path):
    source = tmp_path / 'src/transport_matcher/results/validation.py'
    test = tmp_path / 'tests/test_results.py'
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    source.write_text('original source')
    test.write_text('original test')
    data = dict(schema_version=1, started_at=datetime.now(timezone.utc).isoformat(),
                source_path=source.relative_to(tmp_path).as_posix(), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                tests_sha256={test.relative_to(tmp_path).as_posix(): hashlib.sha256(test.read_bytes()).hexdigest()},
                scope='transport_matcher.results.validation.*_position*', total_mutants=2, counts={'killed': 1, 'survived': 1})
    artifact = tmp_path / 'mutation.json'
    artifact.write_text(json.dumps(data))
    assert quality.mutation_evidence(artifact, tmp_path)['score'] == 50
    source.write_text('changed source')
    assert quality.mutation_evidence(artifact, tmp_path)['status'] == 'stale'
    data['counts'] = {'killed': 3, 'survived': -1}
    artifact.write_text(json.dumps(data))
    assert quality.mutation_evidence(artifact, tmp_path)['status'] == 'invalid'


def test_required_coverage_gate_rejects_missing_report(tmp_path, monkeypatch):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    (raw / 'checks.json').write_text(json.dumps({'fingerprints': {'app': 'current', 'engine': 'current'}}))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda root: 'current')
    with pytest.raises(ValueError, match='Missing coverage artifact'):
        quality.coverage_sanity({'app': tmp_path, 'engine': tmp_path}, {})


def test_required_coverage_gate_rejects_source_changed_during_run(tmp_path, monkeypatch):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    (raw / 'checks.json').write_text('{"fingerprints": {"app": "before"}}')
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda root: 'after')
    with pytest.raises(ValueError, match='current source inputs'):
        quality.coverage_sanity({'app': tmp_path}, {})
