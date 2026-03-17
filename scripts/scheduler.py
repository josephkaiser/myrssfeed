import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_pipeline_lock = threading.Lock()
_pipeline_running = False


def is_pipeline_running() -> bool:
    return _pipeline_running


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
    try:
        from scripts.compile_feed import run_compile_feed
        run_compile_feed()
    except Exception:
        logger.exception("Pipeline stage compile_feed failed — aborting.")
        return
    try:
        from scripts.wordrank import run_wordrank
        run_wordrank()
    except Exception:
        logger.exception("Pipeline stage wordrank failed — continuing.")
    try:
        from scripts.visualization import run_visualization
        run_visualization()
    except Exception:
        logger.exception("Pipeline stage visualization failed — continuing.")
    try:
        from scripts.digest import run_digest
        run_digest()
    except Exception:
        logger.exception("Pipeline stage digest failed — continuing.")
    logger.info("Pipeline complete.")


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_pipeline",
        name="Daily pipeline at 6:00 AM local time",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler configured: daily pipeline at 06:00 local time.")
    return scheduler
