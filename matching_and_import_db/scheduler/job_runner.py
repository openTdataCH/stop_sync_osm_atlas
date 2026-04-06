import argparse
import logging
import os
import subprocess
import sys
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
from matching_and_import_db.database.importer import export_stats_after_import, import_to_database
from matching_and_import_db.orchestrator import run_matching

LOGGER = logging.getLogger(__name__)
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
IMPORT_ETA_SECONDS = int(os.getenv("PIPELINE_IMPORT_ETA_SECONDS", "280"))


def _run_subprocess(command: list[str], phase: str, message: str, maintenance: bool = False) -> None:
    set_phase(phase=phase, message=message, maintenance=maintenance)
    LOGGER.info("Running command: %s", " ".join(command))
    env = os.environ.copy()
    # Keep child Python processes unbuffered so their progress logs appear in
    # Docker logs in real time.
    env.setdefault("PYTHONUNBUFFERED", "1")
    completed = subprocess.run(command, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")


def _run_matching_and_import() -> None:
    set_phase(
        phase="matching",
        message="Running matching pipeline",
        maintenance=False,
    )
    matching_output = run_matching()

    set_phase(
        phase="import",
        message="Importing into database (maintenance window)",
        maintenance=True,
        eta_seconds=IMPORT_ETA_SECONDS,
    )
    no_nearby_sloids = import_to_database(matching_output)
    export_stats_after_import(matching_output, matching_output.duplicate_sloid_map, no_nearby_sloids)


def run_pipeline(mode: str, trigger: str = "manual") -> int:
    lock_token = acquire_run_lock()
    if lock_token is None:
        LOGGER.warning("Another pipeline run is already active. Skipping this trigger.")
        return 2

    run_id = start_run(trigger=trigger)
    LOGGER.info("Pipeline run started (run_id=%s, mode=%s)", run_id, mode)

    try:
        refresh_run_lock(lock_token)
        if mode == "full":
            _run_subprocess(
                [sys.executable, "-m", "matching_and_import_db.downloader.get_atlas_data"],
                phase="atlas_download",
                message="Downloading and processing ATLAS + GTFS data",
            )
            refresh_run_lock(lock_token)

            _run_subprocess(
                [sys.executable, "matching_and_import_db/downloader/get_osm_data.py"],
                phase="osm_download",
                message="Downloading and processing OSM data",
            )
            refresh_run_lock(lock_token)

            _run_matching_and_import()

        elif mode == "match-import":
            _run_matching_and_import()

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
