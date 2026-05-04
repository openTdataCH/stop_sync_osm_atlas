import logging

import pytest

from matching_and_import_db.scheduler import job_runner


def test_timed_step_logs_success(caplog):
    with caplog.at_level(logging.INFO, logger="matching_and_import_db.scheduler.job_runner"):
        with job_runner._timed_step("osm_download"):
            pass

    assert "Step osm_download completed successfully in" in caplog.text


def test_timed_step_logs_failure(caplog):
    with pytest.raises(RuntimeError, match="boom"):
        with caplog.at_level(logging.ERROR, logger="matching_and_import_db.scheduler.job_runner"):
            with job_runner._timed_step("osm_download"):
                raise RuntimeError("boom")

    assert "Step osm_download failed after" in caplog.text