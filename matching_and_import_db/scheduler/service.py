import logging
import os
import signal
import sys
from datetime import timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.pipeline_status import set_next_run, set_status
from matching_and_import_db.scheduler.job_runner import run_pipeline

LOGGER = logging.getLogger(__name__)
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
PIPELINE_TIMEZONE = os.getenv("PIPELINE_TIMEZONE", "Europe/Zurich")
PIPELINE_SCHEDULE_HOUR = int(os.getenv("PIPELINE_SCHEDULE_HOUR", "2"))
PIPELINE_SCHEDULE_MINUTE = int(os.getenv("PIPELINE_SCHEDULE_MINUTE", "0"))

scheduler = BlockingScheduler(timezone=PIPELINE_TIMEZONE)


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


def _shutdown(*_args) -> None:
    LOGGER.info("Stopping scheduler service")
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    sys.exit(0)


def main() -> None:
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

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

    trigger = CronTrigger(hour=PIPELINE_SCHEDULE_HOUR, minute=PIPELINE_SCHEDULE_MINUTE, timezone=PIPELINE_TIMEZONE)
    scheduler.add_job(
        _scheduled_job,
        trigger=trigger,
        id="daily_pipeline_update",
        name="Daily data pipeline update",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    _update_next_run_timestamp()
    LOGGER.info(
        "Scheduler started: daily pipeline at %02d:%02d (%s)",
        PIPELINE_SCHEDULE_HOUR,
        PIPELINE_SCHEDULE_MINUTE,
        PIPELINE_TIMEZONE,
    )

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    scheduler.start()


if __name__ == "__main__":
    main()
