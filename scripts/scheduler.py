import logging
import threading
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.helpers import set_setting, get_setting

logger = logging.getLogger(__name__)

_pipeline_lock = threading.Lock()
_pipeline_running = False
_scheduler: BackgroundScheduler | None = None


def is_pipeline_running() -> bool:
    return _pipeline_running


def _record_pipeline_status(status: str) -> None:
    """
    Best-effort helper to persist the last pipeline status.

    Status values are simple strings ("running" | "success" | "error").
    Errors here should never break the scheduler.
    """
    try:
        set_setting("pipeline_last_status", status)
        if status == "success":
            # Record timestamp of last successful run for age display.
            set_setting("pipeline_last_success_ts", datetime.now(timezone.utc).isoformat())
    except Exception:
        logger.exception("Could not record pipeline status %r", status)


def run_pipeline():
    """Run the full daily pipeline: fetch → rank → visualize → digest.

    Silently skips if a run is already in progress (prevents OOM from
    concurrent ollama calls on the Pi).
    """
    global _pipeline_running
    if not _pipeline_lock.acquire(blocking=False):
        logger.info("Pipeline already running — skipping concurrent start.")
        return
    _pipeline_running = True
    _record_pipeline_status("running")
    try:
        _do_pipeline()
    finally:
        _pipeline_running = False
        _pipeline_lock.release()


def run_pipeline_async() -> bool:
    """Start the pipeline in a daemon thread.

    Returns True if started, False if already running.
    """
    if _pipeline_running:
        return False
    t = threading.Thread(target=run_pipeline, daemon=True, name="pipeline")
    t.start()
    return True


def _do_pipeline():
    """Actual pipeline logic (called with lock held)."""
    logger.info("Pipeline starting.")
    had_error = False
    try:
        from scripts.compile_feed import run_compile_feed

        run_compile_feed()
    except Exception:
        had_error = True
        logger.exception("Pipeline stage compile_feed failed — aborting.")
        _record_pipeline_status("error")
        return

    try:
        # Scrape/enrich newly fetched entries before scoring.
        from scripts.scraper import run_scraper

        run_scraper()
    except Exception:
        had_error = True
        logger.exception("Pipeline stage scraper failed — continuing.")

    try:
        from scripts.wordrank import run_wordrank

        run_wordrank()
    except Exception:
        had_error = True
        logger.exception("Pipeline stage wordrank failed — continuing.")
    try:
        from scripts.visualization import run_visualization

        run_visualization()
    except Exception:
        had_error = True
        logger.exception("Pipeline stage visualization failed — continuing.")
    try:
        from scripts.digest import run_digest

        run_digest()
    except Exception:
        had_error = True
        logger.exception("Pipeline stage digest failed — continuing.")

    final_status = "error" if had_error else "success"
    _record_pipeline_status(final_status)
    logger.info("Pipeline complete with status %s.", final_status)


def _parse_schedule_settings() -> tuple[str, int, int]:
    """Return (frequency, hour, minute) from settings with safe defaults."""
    freq = (get_setting("pipeline_schedule_frequency") or "daily").lower()
    time_str = get_setting("pipeline_schedule_time") or "06:00"
    try:
        hour_str, minute_str = time_str.split(":", 1)
        hour = max(0, min(23, int(hour_str)))
        minute = max(0, min(59, int(minute_str)))
    except Exception:
        hour, minute = 6, 0

    if freq not in {"off", "10m", "hourly", "daily"}:
        freq = "daily"
    return freq, hour, minute


def _add_pipeline_job(scheduler: BackgroundScheduler) -> None:
    freq, hour, minute = _parse_schedule_settings()
    if freq == "off":
        logger.info("Scheduler: automatic pipeline disabled via settings.")
        return

    if freq == "10m":
        # Every 10 minutes
        trigger = CronTrigger(minute="*/10")
        name = "Pipeline every 10 minutes"
    elif freq == "hourly":
        # At the chosen minute each hour
        trigger = CronTrigger(minute=minute)
        name = f"Pipeline hourly at minute {minute:02d}"
    else:  # daily
        trigger = CronTrigger(hour=hour, minute=minute)
        name = f"Daily pipeline at {hour:02d}:{minute:02d} local time"

    scheduler.add_job(
        run_pipeline,
        trigger=trigger,
        id="daily_pipeline",
        name=name,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler configured: %s.", name)


def create_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler()
    _add_pipeline_job(scheduler)
    _scheduler = scheduler
    return scheduler


def reconfigure_scheduler() -> None:
    """Re-read schedule settings and update the existing scheduler job.

    Safe to call after settings are saved; no-op if scheduler hasn't started yet.
    """
    global _scheduler
    if not _scheduler:
        return
    try:
        # Remove existing job if present, then add a new one from settings.
        try:
            _scheduler.remove_job("daily_pipeline")
        except Exception:
            # Missing job is fine; we'll just add a new one.
            pass
        _add_pipeline_job(_scheduler)
    except Exception:
        logger.exception("Failed to reconfigure scheduler from settings.")
