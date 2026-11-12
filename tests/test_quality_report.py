"""The dashboard's evidence: this code's commit, a local run first, then what CI published, never a guess."""
import json

import pytest

from backend import version
from backend.services import ci_release, quality_report
from backend.services.quality_report import EvidenceUnavailable, load_evidence
from backend.services.quality_report import download as real_download

SHA = 'a' * 40
CODE_MAP = {'schema_version': 1, 'modules': [], 'contracts': [], 'files': [], 'links': [], 'interface': {}}


def _example_report():
    return {'schema_version': 1, 'generated_at': '2026-11-11T10:00:00+00:00', 'completeness': 'complete',
            'revision': {'app': SHA, 'engine': 'b' * 40}, 'checks': [{'name': 'python-lint', 'status': 'pass'}], 'files': {}, 'tools': {},
            'modules': {'app.test': {
                'criticality': 'high', 'tests': {'status': 'pass'}, 'coverage': {'status': 'measured', 'branches': 99},
                'duplication': {'status': 'pass'}, 'docs': {'status': 'pass', 'satisfied': 4, 'required': 4}, 'architecture': {'status': 'pass'}}}}


def _evidence(report=True, code_map=CODE_MAP):
    return {'schema_version': 1, 'report': _example_report() if report is True else report, 'code_map': code_map}


@pytest.fixture
def at_commit(monkeypatch):
    """The app runs at SHA, as the server's administrator sets it."""
    monkeypatch.setenv('APP_REVISION', SHA)


@pytest.fixture
def published(monkeypatch):
    """What GitHub holds, by commit; ``asked`` lists every download."""
    files, asked = {}, []

    def download(revision):
        asked.append(revision)
        return files.get(revision)

    monkeypatch.setattr(quality_report, 'download', download)
    files[SHA] = json.dumps(_evidence()).encode()
    return files, asked


def test_commit_comes_from_the_environment_then_a_file_then_the_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(version, 'APP_ROOT', tmp_path)
    monkeypatch.delenv('APP_REVISION', raising=False)
    assert version.app_revision() is None
    git = tmp_path / '.git'
    (git / 'refs/heads').mkdir(parents=True)
    (git / 'HEAD').write_text('ref: refs/heads/main\n')
    (git / 'packed-refs').write_text(f"# pack-refs with: peeled\n{'c' * 40} refs/heads/main\n")
    assert version.app_revision() == 'c' * 40
    (git / 'refs/heads/main').write_text('d' * 40 + '\n')
    assert version.app_revision() == 'd' * 40
    (git / 'HEAD').write_text('E' * 40 + '\n')
    assert version.app_revision() == 'e' * 40
    (tmp_path / 'REVISION').write_text('f' * 40 + '\n')
    assert version.app_revision() == 'f' * 40
    monkeypatch.setenv('APP_REVISION', SHA)
    assert version.app_revision() == SHA
    monkeypatch.setenv('APP_REVISION', 'not a commit')
    assert version.app_revision() is None


def test_commit_of_a_linked_worktree_is_read_from_the_shared_folder(tmp_path, monkeypatch):
    monkeypatch.delenv('APP_REVISION', raising=False)
    main, tree = tmp_path / 'main/.git', tmp_path / 'tree'
    (main / 'worktrees/tree').mkdir(parents=True)
    (main / 'refs/heads').mkdir(parents=True)
    (main / 'refs/heads/topic').write_text('c' * 40 + '\n')
    (main / 'worktrees/tree/HEAD').write_text('ref: refs/heads/topic\n')
    (main / 'worktrees/tree/commondir').write_text('../..\n')
    tree.mkdir()
    (tree / '.git').write_text(f"gitdir: {main / 'worktrees/tree'}\n")
    monkeypatch.setattr(version, 'APP_ROOT', tree)
    assert version.app_revision() == 'c' * 40


def test_an_unknown_commit_has_no_evidence_and_asks_nobody(tmp_path, monkeypatch, published):
    monkeypatch.setattr(quality_report, 'app_revision', lambda: None)
    with pytest.raises(EvidenceUnavailable) as error:
        load_evidence(tmp_path)
    assert (error.value.reason, error.value.revision) == ('unknown_commit', None)
    assert published[1] == []


def test_ci_evidence_is_downloaded_once_and_then_read_from_the_cache(tmp_path, at_commit, published, monkeypatch):
    evidence, source, revision = load_evidence(tmp_path)
    assert (source, revision) == ('ci', SHA)
    assert evidence['report']['modules']['app.test']['coverage']['branches'] == 99
    assert json.loads((tmp_path / '.cache/quality' / f'{SHA}.json').read_text()) == evidence
    assert list((tmp_path / '.cache/quality').iterdir()) == [tmp_path / '.cache/quality' / f'{SHA}.json']
    assert load_evidence(tmp_path)[0] == evidence
    # Another worker, or the app after a restart, finds the file and does not ask GitHub.
    monkeypatch.setattr(quality_report, '_loaded', {})
    assert load_evidence(tmp_path)[0] == evidence
    assert published[1] == [SHA]


def test_a_commit_without_results_is_asked_for_again_only_after_a_while(tmp_path, at_commit, published, monkeypatch):
    files, asked = published
    del files[SHA]
    clock = [1000.0]
    monkeypatch.setattr(quality_report.time, 'monotonic', lambda: clock[0])
    for _ in range(3):
        with pytest.raises(EvidenceUnavailable) as error:
            load_evidence(tmp_path)
        assert (error.value.reason, error.value.revision) == ('no_results', SHA)
    assert asked == [SHA]
    # CI finishes; the next question after the pause gets the evidence.
    files[SHA] = json.dumps(_evidence()).encode()
    clock[0] += quality_report.RETRY_SECONDS
    assert load_evidence(tmp_path)[1] == 'ci'
    assert asked == [SHA, SHA]


@pytest.mark.parametrize('body', [
    b'not JSON', b'null', b'{}', json.dumps({'schema_version': 2, 'report': None, 'code_map': CODE_MAP}).encode(),
    json.dumps(_evidence(code_map={'schema_version': 1})).encode(),
    json.dumps(_evidence(report={'modules': []})).encode(),
    json.dumps(_evidence(report={**_example_report(), 'modules': {'app.test': 'pass'}})).encode(),
])
def test_a_published_file_of_another_shape_is_no_evidence_and_is_not_kept(tmp_path, at_commit, published, body):
    published[0][SHA] = body
    with pytest.raises(EvidenceUnavailable, match='no_results'):
        load_evidence(tmp_path)
    assert not (tmp_path / '.cache/quality' / f'{SHA}.json').exists()


def test_a_local_run_wins_and_needs_neither_commit_nor_github(tmp_path, monkeypatch, published):
    monkeypatch.setattr(quality_report, 'app_revision', lambda: None)
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/evidence.json').write_text(json.dumps(_evidence(report=None)))
    evidence, source, revision = load_evidence(tmp_path)
    assert (source, revision, evidence['report']) == ('local', None, None)
    assert evidence['code_map'] == CODE_MAP
    assert published[1] == []


def test_a_broken_local_file_falls_back_to_the_ci_evidence(tmp_path, at_commit, published):
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/evidence.json').write_text('{"schema_version": 1}')
    assert load_evidence(tmp_path)[1] == 'ci'


def test_download_reads_the_release_asset_of_the_commit_and_survives_github_being_away(monkeypatch):
    asked = []

    class Response:
        status_code = 200

        def iter_content(self, size):
            return iter([b'{"a":', b' 1}'])

    def get(url, **options):
        asked.append((url, options['timeout']))
        return Response()

    monkeypatch.setattr(quality_report, 'download', real_download)
    monkeypatch.setattr(ci_release.requests, 'get', get)
    assert quality_report.download(SHA) == b'{"a": 1}'
    assert asked == [(f'https://github.com/openTdataCH/stop_sync_osm_atlas/releases/download/quality-data/quality-{SHA}.json', 10)]
    Response.status_code = 404
    assert quality_report.download(SHA) is None
    Response.status_code = 200
    monkeypatch.setattr(quality_report, 'MAX_BYTES', 4)
    assert quality_report.download(SHA) is None

    def unreachable(url, **options):
        raise ci_release.requests.ConnectionError('no route')

    monkeypatch.setattr(ci_release.requests, 'get', unreachable)
    assert quality_report.download(SHA) is None
