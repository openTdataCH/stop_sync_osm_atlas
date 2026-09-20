import argparse
import contextlib
import logging
import os
import subprocess
import sys
import shlex
import uuid
from pathlib import Path
import threading
import time
from datetime import UTC, datetime
from typing import Optional

from backend.services import data_meta
from backend.services.pipeline_status import (
    acquire_run_lock,
    finish_failure,
    finish_success,
    refresh_run_lock,
    release_run_lock,
    set_data_updated,
    set_phase,
    set_status,
    start_run,
)
from backend.services.time_utils import format_zurich_timestamp, get_zurich_now
from backend.importing.importer import import_bundle, get_refresh_scope_tables
from backend.jobs.job_types import PipelineRunType

LOGGER = logging.getLogger(__name__)
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
IMPORT_ETA_SECONDS = int(os.getenv("PIPELINE_IMPORT_ETA_SECONDS", "150"))
LOCK_TTL_SECONDS = int(os.getenv("PIPELINE_LOCK_TTL_SECONDS", "14400"))
LOCK_HEARTBEAT_SECONDS = int(
    os.getenv("PIPELINE_LOCK_HEARTBEAT_SECONDS", str(max(5, min(60, LOCK_TTL_SECONDS // 4))))
)
def _publish_refresh_scope(run_type: PipelineRunType) -> tuple[list[str], list[str]]:
    rewritten_tables, reused_tables = get_refresh_scope_tables(run_type)
    set_status(
        run_type=run_type.value,
        refresh_scope_tables_rewritten=rewritten_tables,
        refresh_scope_tables_reused=reused_tables,
    )
    return rewritten_tables, reused_tables


@contextlib.contextmanager
def _timed_step(step_name: str):
    started = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed = time.perf_counter() - started
        LOGGER.error("Step %s failed after %.2fs", step_name, elapsed)
        raise
    elapsed = time.perf_counter() - started
    LOGGER.info("Step %s completed successfully in %.2fs", step_name, elapsed)


class _RunLockHeartbeat:
    def __init__(self, lock_token: str, ttl_seconds: int, interval_seconds: int):
        self._lock_token = lock_token
        self._ttl_seconds = ttl_seconds
        self._interval_seconds = max(1, interval_seconds)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pipeline-lock-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                refresh_run_lock(self._lock_token, ttl_seconds=self._ttl_seconds)
            except Exception:
                LOGGER.exception("Failed to refresh pipeline lock heartbeat")


def _run_subprocess(command: list[str], phase: str, message: str, maintenance: bool = False) -> None:
    set_phase(phase=phase, message=message, maintenance=maintenance)
    started = time.perf_counter()
    LOGGER.info("Running command: %s", shlex.join(command))
    env = os.environ.copy()
    # Source acquisition and matching need no access to the application's DB or
    # session secret, even when deployed alongside the scheduler.
    for key in ("DATABASE_URI", "SECRET_KEY", "FLASK_SECRET_KEY"):
        env.pop(key, None)
    # Keep child Python processes unbuffered so their progress logs appear in
    # Docker logs in real time.
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        completed = subprocess.run(command, check=False, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Matching executable {command[0]!r} was not found. Rebuild the scheduler "
            "with `docker compose build scheduler`, then recreate it with "
            "`docker compose up -d --no-deps --force-recreate scheduler`. "
            "For a non-Docker installation, install the engine or set MATCHER_COMMAND "
            "to its executable."
        ) from exc
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        LOGGER.error("Step %s command exited with code %s after %.2fs", phase, completed.returncode, elapsed)
        raise RuntimeError(
            f"Step {phase} failed: command exited with code {completed.returncode}: {' '.join(command)}"
        )
    LOGGER.info("Step %s completed successfully in %.2fs", phase, elapsed)


def _record_data_updated_timestamp(
    run_type: PipelineRunType | None = None,
    rewritten_tables: list[str] | None = None,
    reused_tables: list[str] | None = None,
) -> str:
    last_pipeline_data_import_ended_at = format_zurich_timestamp(get_zurich_now())
    meta_fields = {"last_pipeline_data_import_ended_at": last_pipeline_data_import_ended_at}
    if run_type is not None:
        meta_fields["last_run_type"] = run_type.value
    if rewritten_tables is not None:
        meta_fields["refresh_scope_tables_rewritten"] = list(rewritten_tables)
    if reused_tables is not None:
        meta_fields["refresh_scope_tables_reused"] = list(reused_tables)
    data_meta.update_data_meta(**meta_fields)
    set_data_updated(last_pipeline_data_import_ended_at)
    if run_type is not None:
        set_status(
            run_type=run_type.value,
            refresh_scope_tables_rewritten=list(rewritten_tables or []),
            refresh_scope_tables_reused=list(reused_tables or []),
        )
    LOGGER.info("Data update timestamp saved: %s", last_pipeline_data_import_ended_at)
    return last_pipeline_data_import_ended_at


def _engine_command(mode, destination):
    command = shlex.split(os.getenv('MATCHER_COMMAND', 'transport-matcher'))
    if not command:
        raise ValueError('MATCHER_COMMAND cannot be empty')
    workspace = Path(os.getenv('PIPELINE_WORKSPACE', '.')).resolve()
    args = command + ['swiss', '--workspace', str(workspace), '--output', str(destination)]
    if mode == 'full':
        args.append('--download')
        if os.getenv('PIPELINE_FORCE_FULL_REFRESH', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
            args.append('--force')
    return args


def run_pipeline(mode: str, trigger: str = "manual") -> int:
    lock_token = acquire_run_lock()
    if lock_token is None:
        LOGGER.warning("Another pipeline run is already active. Skipping this trigger.")
        return 2

    heartbeat = _RunLockHeartbeat(
        lock_token=lock_token,
        ttl_seconds=LOCK_TTL_SECONDS,
        interval_seconds=LOCK_HEARTBEAT_SECONDS,
    )
    heartbeat.start()

    run_id = start_run(trigger=trigger)
    LOGGER.info("Pipeline run started (run_id=%s, mode=%s)", run_id, mode)

    try:
        if mode not in {'full', 'match-import', 'import'}:
            raise ValueError(f'Unsupported mode: {mode}')
        run_type = PipelineRunType.COMPLETE
        _publish_refresh_scope(run_type)
        if mode == 'import':
            configured = os.getenv('PIPELINE_BUNDLE')
            if not configured:
                raise ValueError('PIPELINE_BUNDLE is required for import mode')
            destination = Path(configured).resolve()
        else:
            bundle_root = Path(os.getenv('PIPELINE_BUNDLE_DIR', 'data/results')).resolve()
            destination = bundle_root / uuid.uuid4().hex
            _run_subprocess(_engine_command(mode, destination), phase='matching',
                            message='Preparing a complete matching result snapshot')
        refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)
        set_phase(phase='import', message='Validating and staging the new dataset', maintenance=False)
        with _timed_step('import'):
            manifest = import_bundle(destination)
        rewritten, reused = get_refresh_scope_tables(run_type)
        _record_data_updated_timestamp(run_type, rewritten, reused)
        data_meta.update_data_meta(active_run_id=manifest['run_id'], result_schema_version=manifest['schema_version'])

        finish_success(
            message=(
                f"Pipeline run completed successfully ({mode}, {run_type.value}) at "
                f"{datetime.now(UTC).isoformat().replace('+00:00', 'Z')}"
            )
        )
        LOGGER.info("Pipeline run finished successfully")
        return 0

    except Exception as exc:
        error_message = str(exc)
        finish_failure(error_message)
        LOGGER.exception("Pipeline run failed: %s", error_message)
        return 1

    finally:
        heartbeat.stop()
        release_run_lock(lock_token)


def main() -> None:
    # Force root logger configuration so INFO logs are visible when invoked via
    # docker exec or imported from scheduler service.
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )

    parser = argparse.ArgumentParser(description="Run data pipeline with status + lock integration.")
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "match-import", "import"],
        help="full downloads/matches/imports; match-import reuses sources; import consumes PIPELINE_BUNDLE",
    )
    parser.add_argument(
        "--trigger",
        default="manual",
        choices=["manual", "scheduled"],
        help="Run trigger type for status reporting",
    )
    args = parser.parse_args()

    sys.exit(run_pipeline(mode=args.mode, trigger=args.trigger))


if __name__ == "__main__":
    main()
