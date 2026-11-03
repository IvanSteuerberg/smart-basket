"""`smart-basket-worker`: APScheduler process of the `worker` service (decision 0008)."""

import logging
import signal

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from smart_basket.config import get_settings
from smart_basket.worker import jobs

log = logging.getLogger("smart_basket.worker")


def build_scheduler() -> BlockingScheduler:
    tz = get_settings().timezone
    scheduler = BlockingScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1})
    # Times are placeholders until the first ingestion runs set rate and frequency (0006).
    scheduler.add_job(
        jobs.ingest_catalogs, CronTrigger(hour=5, minute=7, timezone=tz), id="ingest_catalogs"
    )
    scheduler.add_job(
        jobs.match_products, CronTrigger(hour=7, minute=7, timezone=tz), id="match_products"
    )
    scheduler.add_job(jobs.refresh_bi, CronTrigger(hour=7, minute=37, timezone=tz), id="refresh_bi")
    scheduler.add_job(
        jobs.ensure_price_history_partitions,
        CronTrigger(day=1, hour=3, minute=17, timezone=tz),
        id="ensure_price_history_partitions",
    )
    return scheduler


def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    scheduler = build_scheduler()

    def stop(signum: int, _frame: object) -> None:
        log.info("signal %s received, shutting down", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, stop)
    try:
        jobs.ensure_price_history_partitions()
    except Exception:
        log.exception("could not check price_history partitions; will retry on schedule")
    for job in scheduler.get_jobs():
        log.info("scheduled %s: %s", job.id, job.trigger)
    scheduler.start()


if __name__ == "__main__":
    main()
