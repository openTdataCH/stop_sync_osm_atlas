"""Optional structured progress around application-owned import work."""
from __future__ import annotations

from contextlib import contextmanager
import logging
import time

from backend.services.pipeline_progress import PROGRESS_SCHEMA_VERSION


def report(callback, *args):
    """Progress delivery cannot change the outcome of a database transaction."""
    if callback is not None:
        try:
            callback(*args)
        except Exception:
            logging.getLogger(__name__).exception("Could not report import progress")


@contextmanager
def progress_stage(stage_id, callback=None):
    started = time.perf_counter()

    def emit(event, **extra):
        report(callback, {
                "event": event,
                "progress_schema_version": PROGRESS_SCHEMA_VERSION,
                "stage_id": stage_id,
                "seconds": round(time.perf_counter() - started, 3),
                **extra,
            })

    emit("stage_started")
    try:
        yield
    except BaseException as exc:
        emit("stage_failed", error=str(exc))
        raise
    else:
        emit("stage_finished")
