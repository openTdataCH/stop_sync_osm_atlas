#!/usr/bin/env python3
"""Commit and push the CI quality report of the latest pushed commit, ready for a deployment.

The deployment builds from this checkout, so the report must be committed to reach it.
The report commit only touches quality/published/, which CI ignores and the page does
not count as changed code.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.quality_report import PUBLISHED, shipped_fingerprint  # noqa: E402

WORKFLOW = 'tests.yml'
BRANCH = 'main'


def fail(message):
    sys.exit(f'deploy-report: {message}')


def run(*command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        fail(f"`{' '.join(command)}` failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def committed_files(sha):
    """Files exactly as committed, independent of the working tree; the fingerprint keeps the shipped ones."""
    archive = subprocess.run(['git', 'archive', '--format=tar', sha], cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        return [(member.name, tar.extractfile(member).read()) for member in tar if member.isfile()]


def main():
    sha = run('git', 'rev-parse', 'HEAD')
    short = sha[:7]
    touched = run('git', 'diff-tree', '--no-commit-id', '--name-only', '-r', sha).split('\n')
    if all(name.startswith(f'{PUBLISHED}/') for name in touched if name):
        fail(f'{short} is already a quality report commit. Nothing new to publish.')
    run('git', 'fetch', '--quiet', 'origin', BRANCH)
    if run('git', 'rev-parse', f'origin/{BRANCH}') != sha:
        fail(f'HEAD {short} is not origin/{BRANCH}. Push your commits (or pull) first, so CI has measured exactly this commit.')
    runs = json.loads(run('gh', 'run', 'list', '--workflow', WORKFLOW, '--commit', sha, '--event', 'push',
                          '--limit', '1', '--json', 'databaseId,status,conclusion,url'))
    if not runs:
        fail(f'no CI run for {short} yet. Wait a moment for GitHub to start it, then retry.')
    ci = runs[0]
    if ci['status'] != 'completed':
        fail(f"CI for {short} is still running: {ci['url']}. Retry when it finishes.")
    if ci['conclusion'] != 'success':
        fail(f"CI for {short} did not pass ({ci['conclusion']}): {ci['url']}. Fix it and push before deploying.")
    with tempfile.TemporaryDirectory() as directory:
        run('gh', 'run', 'download', str(ci['databaseId']), '--name', f'quality-{sha}', '--dir', directory)
        report_text = (Path(directory) / 'latest.json').read_text()
        code_map = Path(directory) / 'code-map.json'
        if not code_map.is_file():
            fail(f"the CI artifact of {short} has no code-map.json, which the dashboard draws. Rerun CI on this commit.")
        code_map_text = code_map.read_text()
    report = json.loads(report_text)
    if report.get('revision', {}).get('app') != sha:
        fail(f"the CI report measured {report.get('revision', {}).get('app')}, not {sha}.")
    published = ROOT / PUBLISHED
    published.mkdir(parents=True, exist_ok=True)
    (published / 'latest.json').write_text(report_text)
    (published / 'code-map.json').write_text(code_map_text)
    publication = {'app_revision': sha, 'run_url': ci['url'], 'shipped_fingerprint': shipped_fingerprint(committed_files(sha))}
    (published / 'publication.json').write_text(json.dumps(publication, indent=2, sort_keys=True) + '\n')
    run('git', 'add', '--', PUBLISHED)
    run('git', 'commit', '--quiet', '-m', f'Record quality report for {short}', '--', PUBLISHED)
    run('git', 'push', '--quiet', 'origin', f'HEAD:{BRANCH}')
    print(f'Published the quality report for {short} ({ci["url"]}). The deployment can now be built from {BRANCH}.')


if __name__ == '__main__':
    main()
