"""`make deploy-report` must publish only a passing CI report for exactly the pushed commit."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from backend.services import quality_report
from scripts import deploy_report

SHA = 'a' * 40
RUN = {'databaseId': 7, 'status': 'completed', 'conclusion': 'success', 'url': 'https://github.com/example/actions/runs/7'}


def _fake_git_and_gh(monkeypatch, tmp_path, ci_run=RUN, touched='backend/app.py', measured=SHA, code_map=True):
    calls = []

    def run(*command):
        calls.append(command)
        if command[:2] == ('git', 'rev-parse'):
            return SHA
        if command[:2] == ('git', 'diff-tree'):
            return touched
        if command[:3] == ('gh', 'run', 'list'):
            return json.dumps([ci_run] if ci_run else [])
        if command[:3] == ('gh', 'run', 'download'):
            directory = Path(command[command.index('--dir') + 1])
            report = {'schema_version': 1, 'revision': {'app': measured, 'engine': 'e'}, 'modules': {}}
            (directory / 'latest.json').write_text(json.dumps(report))
            if code_map:
                (directory / 'code-map.json').write_text(json.dumps({'schema_version': 1}))
        return ''

    monkeypatch.setattr(deploy_report, 'ROOT', tmp_path)
    monkeypatch.setattr(deploy_report, 'run', run)
    monkeypatch.setattr(deploy_report, 'committed_files', lambda sha: [('backend/app.py', b'app')])
    return calls


def test_publishes_the_passing_report_and_commits_only_the_published_folder(tmp_path, monkeypatch):
    calls = _fake_git_and_gh(monkeypatch, tmp_path)
    deploy_report.main()
    published = tmp_path / quality_report.PUBLISHED
    publication = json.loads((published / 'publication.json').read_text())
    assert publication == {'app_revision': SHA, 'run_url': RUN['url'],
                           'shipped_fingerprint': quality_report.shipped_fingerprint([('backend/app.py', b'app')])}
    assert json.loads((published / 'latest.json').read_text())['revision']['app'] == SHA
    assert json.loads((published / 'code-map.json').read_text()) == {'schema_version': 1}
    assert f"[CI run]({RUN['url']})" in (published / 'report.md').read_text()
    commit = next(command for command in calls if command[:2] == ('git', 'commit'))
    assert commit[-2:] == ('--', quality_report.PUBLISHED)
    assert calls[-1] == ('git', 'push', '--quiet', 'origin', 'HEAD:main')


@pytest.mark.parametrize('ci_run,message', [
    (None, 'no CI run'),
    ({**RUN, 'status': 'in_progress'}, 'still running'),
    ({**RUN, 'conclusion': 'failure'}, 'did not pass'),
])
def test_refuses_without_a_passing_ci_run(tmp_path, monkeypatch, ci_run, message):
    calls = _fake_git_and_gh(monkeypatch, tmp_path, ci_run=ci_run)
    with pytest.raises(SystemExit, match=message):
        deploy_report.main()
    assert not (tmp_path / quality_report.PUBLISHED).exists()
    assert not any(command[:2] in {('git', 'commit'), ('git', 'push')} for command in calls)


def test_refuses_a_report_for_another_commit(tmp_path, monkeypatch):
    _fake_git_and_gh(monkeypatch, tmp_path, measured='b' * 40)
    with pytest.raises(SystemExit, match='measured'):
        deploy_report.main()
    assert not (tmp_path / quality_report.PUBLISHED).exists()


def test_refuses_an_artifact_without_the_code_map(tmp_path, monkeypatch):
    _fake_git_and_gh(monkeypatch, tmp_path, code_map=False)
    with pytest.raises(SystemExit, match='no code-map.json'):
        deploy_report.main()
    assert not (tmp_path / quality_report.PUBLISHED).exists()


def test_refuses_when_head_is_already_a_report_commit(tmp_path, monkeypatch):
    calls = _fake_git_and_gh(monkeypatch, tmp_path, touched='quality/published/latest.json\nquality/published/report.md')
    with pytest.raises(SystemExit, match='already a quality report commit'):
        deploy_report.main()
    assert not any(command[:2] == ('gh', 'run') for command in calls)


@pytest.mark.skipif(shutil.which('git') is None, reason='needs the git executable')
def test_committed_fingerprint_matches_a_checkout_of_that_commit(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)

    git('init', '--quiet')
    for name in ('backend/app.py', 'templates/page.html', 'engine.ref', 'tests/test_app.py'):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(name)
    git('add', '.')
    git('-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '--quiet', '-m', 'code')
    sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    (tmp_path / 'backend/__pycache__').mkdir()
    (tmp_path / 'backend/__pycache__/app.cpython-313.pyc').write_bytes(b'bytecode')
    monkeypatch.setattr(deploy_report, 'ROOT', tmp_path)
    assert (quality_report.shipped_fingerprint(deploy_report.committed_files(sha))
            == quality_report.shipped_fingerprint(quality_report.shipped_files(tmp_path)))
