import argparse
import contextlib
import logging
import os
import subprocess
import sys
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
from matching_and_import_db.downloader.get_atlas_data import (
    ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK,
    get_current_gtfs_permalink,
)
from matching_and_import_db.downloader.source_freshness import (
    preprocessing_sources_unchanged,
    probe_remote_source,
    source_snapshot_is_usable,
)
from matching_and_import_db.database.importer import (
    atlas_cached_static_tables_ready,
    build_fast_insert_payloads,
    export_stats_after_import,
    get_refresh_scope_tables,
    import_to_database,
    print_problem_summary,
    precompute_problem_artifacts,
    precompute_route_artifacts,
)
from matching_and_import_db.database.session import session
from matching_and_import_db.orchestrator import run_matching
from matching_and_import_db.scheduler.job_types import PipelineRunType

LOGGER = logging.getLogger(__name__)
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
IMPORT_ETA_SECONDS = int(os.getenv("PIPELINE_IMPORT_ETA_SECONDS", "150"))
LOCK_TTL_SECONDS = int(os.getenv("PIPELINE_LOCK_TTL_SECONDS", "14400"))
LOCK_HEARTBEAT_SECONDS = int(
    os.getenv("PIPELINE_LOCK_HEARTBEAT_SECONDS", str(max(5, min(60, LOCK_TTL_SECONDS // 4))))
)
PREPROCESSING_META_KEY = "preprocessing_sources"


def _force_full_refresh_enabled() -> bool:
    return os.getenv("PIPELINE_FORCE_FULL_REFRESH", "").strip().lower() in {"1", "true", "yes", "on"}


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
    LOGGER.info("Running command: %s", " ".join(command))
    env = os.environ.copy()
    # Keep child Python processes unbuffered so their progress logs appear in
    # Docker logs in real time.
    env.setdefault("PYTHONUNBUFFERED", "1")
    completed = subprocess.run(command, check=False, env=env)
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


def _load_preprocessing_source_state() -> dict:
    return data_meta.load_data_meta().get(PREPROCESSING_META_KEY) or {}


def _probe_preprocessing_sources() -> dict:
    gtfs_url = get_current_gtfs_permalink()
    return {
        "atlas": probe_remote_source("atlas", ATLAS_ACTUAL_DATE_RESOURCE_PERMALINK),
        "gtfs": probe_remote_source("gtfs", gtfs_url),
    }


def _persist_preprocessing_source_state(source_state: dict) -> None:
    downloaded_at = format_zurich_timestamp(get_zurich_now())
    payload = {
        "atlas": {
            **(source_state.get("atlas") or {}),
            "atlas_downloaded_at": downloaded_at,
        },
        "gtfs": {
            **(source_state.get("gtfs") or {}),
            "gtfs_downloaded_at": downloaded_at,
        },
        "preprocessing_completed_at": downloaded_at,
    }
    data_meta.update_data_meta(**{PREPROCESSING_META_KEY: payload})
    LOGGER.info("Persisted ATLAS/GTFS preprocessing source validators")


def _preprocessing_sources_ready(source_state: dict) -> bool:
    return all(source_snapshot_is_usable(source_state.get(source_name)) for source_name in ("atlas", "gtfs"))


def _run_atlas_gtfs_preprocessing_if_needed(lock_token: str) -> PipelineRunType:
    set_phase(
        phase="source_probe",
        message="Checking ATLAS + GTFS source freshness",
        maintenance=False,
    )
    current_sources = _probe_preprocessing_sources()
    previous_sources = _load_preprocessing_source_state()

    if preprocessing_sources_unchanged(previous_sources, current_sources):
        if _force_full_refresh_enabled():
            set_phase(
                phase="atlas_download",
                message="ATLAS + GTFS unchanged; forcing preprocessing rebuild and full refresh",
                maintenance=False,
            )
            LOGGER.info("ATLAS and GTFS sources unchanged, but preprocessing and full refresh are forced by environment")
        else:
            if atlas_cached_static_tables_ready(session):
                set_phase(
                    phase="atlas_download",
                    message="ATLAS + GTFS unchanged; reusing cached preprocessing outputs",
                    maintenance=False,
                )
                LOGGER.info("ATLAS and GTFS sources unchanged; skipping preprocessing download step")
                return PipelineRunType.ATLAS_CACHED

            set_phase(
                phase="atlas_download",
                message="ATLAS + GTFS unchanged; cached preprocessing found, rebuilding static import tables",
                maintenance=False,
            )
            LOGGER.info(
                "ATLAS and GTFS sources unchanged, but static import tables are missing/empty; "
                "running cached bootstrap refresh"
            )
            return PipelineRunType.ATLAS_CACHED_BOOTSTRAP

    _run_subprocess(
        [sys.executable, "-m", "matching_and_import_db.downloader.get_atlas_data"],
        phase="atlas_download",
        message="Downloading and processing ATLAS + GTFS data",
    )
    refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

    source_state_to_persist = current_sources if _preprocessing_sources_ready(current_sources) else _probe_preprocessing_sources()
    if _preprocessing_sources_ready(source_state_to_persist):
        _persist_preprocessing_source_state(source_state_to_persist)
    else:
        LOGGER.warning("ATLAS/GTFS preprocessing succeeded, but source validators could not be persisted")
    return PipelineRunType.COMPLETE


def _run_matching_and_import(lock_token: str, run_type: PipelineRunType) -> None:
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
        message=f"Importing into database ({run_type.value} maintenance window)",
        maintenance=True,
        eta_seconds=IMPORT_ETA_SECONDS,
    )
    with _timed_step("import"):
        no_nearby_sloids = import_to_database(db_payloads=db_payloads, run_type=run_type)
    refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

    rewritten_tables, reused_tables = get_refresh_scope_tables(run_type)
    _record_data_updated_timestamp(
        run_type=run_type,
        rewritten_tables=rewritten_tables,
        reused_tables=reused_tables,
    )
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
        run_type = PipelineRunType.COMPLETE
        _publish_refresh_scope(run_type)
        refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)
        if mode == "full":
            run_type = _run_atlas_gtfs_preprocessing_if_needed(lock_token)
            _publish_refresh_scope(run_type)
            refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

            _run_subprocess(
                [sys.executable, "-m", "matching_and_import_db.downloader.get_osm_data"],
                phase="osm_download",
                message="Downloading and processing OSM data",
            )
            refresh_run_lock(lock_token, ttl_seconds=LOCK_TTL_SECONDS)

            _run_matching_and_import(lock_token, run_type)

        elif mode == "match-import":
            _publish_refresh_scope(run_type)
            _run_matching_and_import(lock_token, run_type)

        else:
            raise ValueError(f"Unsupported mode: {mode}")

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
