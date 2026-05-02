import logging
import os
import signal
import sys
from datetime import timezone
from typing import Optional

from apscheduler.events import EVENT_SCHEDULER_STARTED
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.services.pipeline_status import set_next_run, set_status
from matching_and_import_db.scheduler.job_runner import run_pipeline

LOGGER = logging.getLogger(__name__)
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
PIPELINE_TIMEZONE = os.getenv("PIPELINE_TIMEZONE", "Europe/Zurich")


def _load_schedule_interval_hours() -> int:
    interval_hours = int(os.getenv("PIPELINE_SCHEDULE_INTERVAL_HOURS", "24"))
    if interval_hours < 1:
        raise ValueError("PIPELINE_SCHEDULE_INTERVAL_HOURS must be >= 1")
    return interval_hours


PIPELINE_SCHEDULE_INTERVAL_HOURS = _load_schedule_interval_hours()

scheduler = BlockingScheduler(timezone=PIPELINE_TIMEZONE)


def _create_interval_trigger(interval_hours: Optional[int] = None) -> IntervalTrigger:
    return IntervalTrigger(
        hours=interval_hours or PIPELINE_SCHEDULE_INTERVAL_HOURS,
        timezone=PIPELINE_TIMEZONE,
    )


def _update_next_run_timestamp() -> None:
    job = scheduler.get_job("daily_pipeline_update")
    if not job:
        set_next_run(None)
        return

    # APScheduler versions may expose next execution time under different names.
    next_run = getattr(job, "next_run_time", None)
    if next_run is None:
        next_run = getattr(job, "next_fire_time", None)

    if next_run:
        set_next_run(next_run.astimezone(timezone.utc).isoformat())
        return

    set_next_run(None)


def _scheduled_job() -> None:
    _update_next_run_timestamp()
    run_pipeline(mode="full", trigger="scheduled")
    _update_next_run_timestamp()


def _handle_scheduler_started(_event=None) -> None:
    _update_next_run_timestamp()


def _shutdown(*_args) -> None:
    LOGGER.info("Stopping scheduler service")
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    sys.exit(0)


def main() -> None:
    # Force root logger configuration so INFO logs are visible even if another
    # module configured logging before scheduler startup.
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )

    set_status(
        status="idle",
        phase="idle",
        message="Scheduler service online",
        maintenance=False,
        run_id=None,
        trigger=None,
        started_at=None,
        finished_at=None,
        processed=None,
        total=None,
        eta_seconds=None,
    )

    trigger = _create_interval_trigger()
    scheduler.add_job(
        _scheduled_job,
        trigger=trigger,
        id="daily_pipeline_update",
        name="Recurring data pipeline update",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_listener(_handle_scheduler_started, EVENT_SCHEDULER_STARTED)

    _update_next_run_timestamp()
    LOGGER.info(
        "Scheduler started: pipeline every %d hour(s) (%s)",
        PIPELINE_SCHEDULE_INTERVAL_HOURS,
        PIPELINE_TIMEZONE,
    )

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    scheduler.start()


if __name__ == "__main__":
    main()
