import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from utils.helpers import get_db, set_setting, get_setting

logger = logging.getLogger(__name__)

_pipeline_lock = threading.Lock()
_pipeline_running = False
_scheduler: Optional[BackgroundScheduler] = None


def is_pipeline_running() -> bool:
    return _pipeline_running


def _run_pipeline_stages(stages: list[tuple[str, Callable[[], None]]]) -> bool:
    """Run pipeline stages in order and keep going after individual failures."""
    had_error = False
    for stage_name, stage_fn in stages:
        try:
            stage_fn()
        except Exception:
            had_error = True
            logger.exception("Pipeline stage %s failed — continuing with remaining stages.", stage_name)
    return had_error


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
    """Actual pipeline logic (called with lock held).

    Streamlined for the Pi: just fetch feeds and apply lightweight quality
    scoring. Heavy stages (WordRank, visualization, digest, newsletters,
    scraper) are intentionally omitted.
    """
    logger.info("Pipeline starting (minimal mode).")
    had_error = False

    try:
        from scripts.compile_feed import run_compile_feed
    except Exception:
        had_error = True
        logger.exception("Pipeline stage compile_feed failed to load.")
    else:
        had_error = _run_pipeline_stages([("compile_feed", run_compile_feed)]) or had_error

    try:
        from scripts.quality_score import run_quality_score
    except Exception:
        had_error = True
        logger.exception("Pipeline stage quality_score failed to load.")
    else:
        had_error = _run_pipeline_stages([("quality_score", run_quality_score)]) or had_error

    final_status = "error" if had_error else "success"
    _record_pipeline_status(final_status)
    logger.info("Pipeline complete with status %s.", final_status)


def _get_persisted_setting(key: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row["value"] if row else None


def _parse_pipeline_refresh_minutes() -> int:
    """Return the automatic refresh interval in minutes.

    New installs use `pipeline_refresh_minutes`. Older databases may still
    have the legacy schedule keys, so keep a compatibility fallback.
    """
    raw = _get_persisted_setting("pipeline_refresh_minutes")
    if raw is not None:
        try:
            return max(5, min(1440, int(raw)))
        except (TypeError, ValueError):
            return 15

    legacy_freq = (_get_persisted_setting("pipeline_schedule_frequency") or "").strip().lower()
    if legacy_freq == "off":
        return 0
    if legacy_freq == "10m":
        return 10
    if legacy_freq == "hourly":
        return 60
    if legacy_freq == "daily":
        return 1440

    raw_default = get_setting("pipeline_refresh_minutes") or "15"
    try:
        return max(5, min(1440, int(raw_default)))
    except (TypeError, ValueError):
        return 15


def _add_pipeline_job(scheduler: BackgroundScheduler) -> None:
    minutes = _parse_pipeline_refresh_minutes()
    if minutes <= 0:
        logger.info("Scheduler: automatic refresh disabled via settings.")
        return

    trigger = IntervalTrigger(minutes=minutes)
    name = f"Automatic refresh every {minutes} minutes"

    scheduler.add_job(
        run_pipeline,
        trigger=trigger,
        id="pipeline_refresh",
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
            _scheduler.remove_job("pipeline_refresh")
        except Exception:
            # Missing job is fine; we'll just add a new one.
            pass
        try:
            _scheduler.remove_job("newsletter_poll")
        except Exception:
            pass
        _add_pipeline_job(_scheduler)
        _add_newsletter_job(_scheduler)
    except Exception:
        logger.exception("Failed to reconfigure scheduler from settings.")
