import sys
import logging
import subprocess
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def _daily_job():
    from scripts.compile_feed import run_compile_feed
    from scripts.cluster_topics import start_job, finish_job

    run_compile_feed()

    # Run clustering in a child process so an OOM-kill on the Pi doesn't
    # bring down the scheduler / web server with it.
    job_id = start_job()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.cluster_topics", "--job-id", str(job_id)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            finish_job(job_id, success=False)
            logger.error(
                "Scheduled clustering child exited %d:\n%s",
                proc.returncode, proc.stderr,
            )
        else:
            logger.info("Scheduled clustering complete.")
    except subprocess.TimeoutExpired:
        finish_job(job_id, success=False)
        logger.error("Scheduled clustering timed out after 10 minutes.")
    except Exception:
        finish_job(job_id, success=False)
        logger.exception("Scheduled clustering failed.")


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _daily_job,
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_feed_compile",
        name="Fetch RSS feeds and cluster topics at 6:00 AM local time",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler configured: RSS fetch + topic cluster daily at 06:00 local time.")
    return scheduler
