import argparse
import contextlib
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from backend.services.pipeline_status import (
    acquire_run_lock,
    finish_failure,
    finish_success,
    refresh_run_lock,
    release_run_lock,
    set_phase,
    start_run,
)
from matching_and_import_db.database.importer import (
    build_fast_insert_payloads,
    export_stats_after_import,
    import_to_database,
    print_problem_summary,
    precompute_problem_artifacts,
    precompute_route_artifacts,
)
from matching_and_import_db.orchestrator import run_matching

LOGGER = logging.getLogger(__name__)
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
IMPORT_ETA_SECONDS = int(os.getenv("PIPELINE_IMPORT_ETA_SECONDS", "280"))
LOCK_TTL_SECONDS = int(os.getenv("PIPELINE_LOCK_TTL_SECONDS", "14400"))
LOCK_HEARTBEAT_SECONDS = int(
    os.getenv("PIPELINE_LOCK_HEARTBEAT_SECONDS", str(max(5, min(60, LOCK_TTL_SECONDS // 4))))
)


@contextlib.contextmanager
def _timed_step(step_name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        LOGGER.info("Step %s completed in %.2fs", step_name, elapsed)


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
    with _timed_step(phase):
        LOGGER.info("Running command: %s", " ".join(command))
        env = os.environ.copy()
        # Keep child Python processes unbuffered so their progress logs appear in
        # Docker logs in real time.
        env.setdefault("PYTHONUNBUFFERED", "1")
        completed = subprocess.run(command, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")


def _run_matching_and_import(lock_token: str) -> None:
    set_phase(
        phase="matching",
        message="Running matching pipeline",
        maintenance=False,
    )
    with _timed_step("matching"):
        matching_output = run_matching()
    refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

    set_phase(
        phase="problem_precompute",
        message="Precomputing problem detection results",
        maintenance=False,
    )
    with _timed_step("problem_precompute"):
        problem_artifacts = precompute_problem_artifacts(matching_output)
    refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

    set_phase(
        phase="route_route_precompute",
        message="Precomputing route-route linking payload",
        maintenance=False,
    )
    with _timed_step("route_route_precompute"):
        route_artifacts = precompute_route_artifacts(matching_output)
    refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

    # Build all row dictionaries BEFORE entering the blocking maintenance window.
    # This moves all CPU-bound work (coordinate formatting, duplicate resolution,
    # problem attachment, trio-middle detection) out of the blocking phase.
    set_phase(
        phase="payload_precompute",
        message="Preparing database write payloads",
        maintenance=False,
    )
    with _timed_step("payload_precompute"):
        db_payloads = build_fast_insert_payloads(
            matching_output,
            problem_artifacts,
            route_artifacts,
        )
    refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

    # Blocking maintenance: only TRUNCATE + bulk INSERT, zero Python logic.
    set_phase(
        phase="import",
        message="Importing into database (maintenance window)",
        maintenance=True,
        eta_seconds=IMPORT_ETA_SECONDS,
    )
    with _timed_step("import"):
        no_nearby_sloids = import_to_database(db_payloads=db_payloads)
    refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

    set_phase(
        phase="stats_finalize",
        message="Finalizing statistics",
        maintenance=False,
    )
    with _timed_step("stats_finalize"):
        print_problem_summary()
        export_stats_after_import(matching_output, matching_output.duplicate_sloid_map, no_nearby_sloids)


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
        refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)
        if mode == "full":
            _run_subprocess(
                [sys.executable, "-m", "matching_and_import_db.downloader.get_atlas_data"],
                phase="atlas_download",
                message="Downloading and processing ATLAS + GTFS data",
            )
            refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

            _run_subprocess(
                [sys.executable, "matching_and_import_db/downloader/get_osm_data.py"],
                phase="osm_download",
                message="Downloading and processing OSM data",
            )
            refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

            _run_matching_and_import(lock_token)

        elif mode == "match-import":
            _run_matching_and_import(lock_token)

        else:
            raise ValueError(f"Unsupported mode: {mode}")

        finish_success(
            message=(
                f"Pipeline run completed successfully ({mode}) at "
                f"{datetime.utcnow().isoformat()}Z"
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
        choices=["full", "match-import"],
        help="Pipeline mode: full (download + match + import) or match-import (reuse existing downloaded data)",
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
