import logging

import pytest

from backend.jobs import job_runner


def test_timed_step_logs_success(caplog):
    with caplog.at_level(logging.INFO, logger="backend.jobs.job_runner"):
        with job_runner._timed_step("osm_download"):
            pass

    assert "Step osm_download completed successfully in" in caplog.text


def test_timed_step_logs_failure(caplog):
    with pytest.raises(RuntimeError, match="boom"):
        with caplog.at_level(logging.ERROR, logger="backend.jobs.job_runner"):
            with job_runner._timed_step("osm_download"):
                raise RuntimeError("boom")

    assert "Step osm_download failed after" in caplog.text


def test_missing_engine_explains_how_to_rebuild_scheduler(monkeypatch):
    monkeypatch.setattr(job_runner, 'set_phase', lambda **kwargs: None)

    def missing_executable(command, **kwargs):
        raise FileNotFoundError(2, 'No such file or directory', command[0])

    monkeypatch.setattr(job_runner.subprocess, 'run', missing_executable)
    with pytest.raises(RuntimeError, match='docker compose build scheduler') as error:
        job_runner._run_subprocess(['transport-matcher', 'swiss'], 'matching', 'Matching')
    assert '--force-recreate scheduler' in str(error.value)
    assert 'MATCHER_COMMAND' in str(error.value)
