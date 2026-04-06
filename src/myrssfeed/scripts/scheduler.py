import copy
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from myrssfeed.utils.helpers import get_db, set_setting, get_setting

logger = logging.getLogger(__name__)

_pipeline_lock = threading.Lock()
_pipeline_progress_lock = threading.Lock()
_pipeline_running = False
_scheduler: Optional[BackgroundScheduler] = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_pipeline_progress() -> dict:
    return {
        "running": False,
        "stage": "idle",
        "stage_label": "Ready",
        "message": "",
        "started_at": None,
        "updated_at": None,
        "total_feeds": 0,
        "completed_feeds": 0,
        "current_feed": None,
        "results": [],
        "total_items_seen": 0,
        "total_new_entries": 0,
        "pruned_entries": 0,
        "quality_updates": 0,
        "theme_updates": 0,
    }


_pipeline_progress: dict = _empty_pipeline_progress()


def is_pipeline_running() -> bool:
    return _pipeline_running


def _mutate_pipeline_progress(mutator: Callable[[dict], None]) -> None:
    with _pipeline_progress_lock:
        mutator(_pipeline_progress)
        _pipeline_progress["updated_at"] = _utc_now_iso()


def _replace_pipeline_progress(next_state: dict) -> None:
    global _pipeline_progress
    with _pipeline_progress_lock:
        _pipeline_progress = next_state


def get_pipeline_progress() -> dict:
    with _pipeline_progress_lock:
        snapshot = copy.deepcopy(_pipeline_progress)

    total_feeds = int(snapshot.get("total_feeds") or 0)
    completed_feeds = int(snapshot.get("completed_feeds") or 0)
    if total_feeds > 0:
        ratio = completed_feeds / max(1, total_feeds)
        progress_percent = int(max(0, min(100, round(ratio * 100))))
    elif snapshot.get("stage") in {"quality_score", "theme_labeling", "complete", "error"}:
        progress_percent = 100
    else:
        progress_percent = 0
    snapshot["progress_percent"] = progress_percent
    return snapshot


def _initialize_pipeline_progress() -> None:
    started_at = _utc_now_iso()
    _replace_pipeline_progress(
        {
            **_empty_pipeline_progress(),
            "running": True,
            "stage": "starting",
            "stage_label": "Preparing refresh",
            "message": "Preparing refresh…",
            "started_at": started_at,
            "updated_at": started_at,
        }
    )


def _refresh_message(snapshot: dict) -> str:
    total_feeds = int(snapshot.get("total_feeds") or 0)
    completed_feeds = int(snapshot.get("completed_feeds") or 0)
    total_new_entries = int(snapshot.get("total_new_entries") or 0)
    if snapshot.get("stage") == "compile_feed":
        current = snapshot.get("current_feed") or {}
        title = current.get("title") or current.get("url") or "feed"
        return f"Refreshing {title} ({completed_feeds}/{total_feeds})"
    if snapshot.get("stage") == "quality_score":
        return "Scoring articles…"
    if snapshot.get("stage") == "theme_labeling":
        return "Applying theme labels…"
    if snapshot.get("stage") == "complete":
        return (
            f"Fetched {completed_feeds}/{total_feeds} feeds, "
            f"stored {total_new_entries} new entries."
        )
    if snapshot.get("stage") == "error":
        return f"Refresh finished with issues ({completed_feeds}/{total_feeds} feeds)."
    return snapshot.get("message") or ""


def _handle_compile_progress(event: str, payload: dict) -> None:
    if event == "start":
        def apply(snapshot: dict) -> None:
            snapshot["stage"] = "compile_feed"
            snapshot["stage_label"] = "Refreshing feeds"
            snapshot["message"] = f"Refreshing {payload.get('total_feeds', 0)} feeds…"
            snapshot["total_feeds"] = int(payload.get("total_feeds") or 0)
            snapshot["completed_feeds"] = int(payload.get("completed_feeds") or 0)
            snapshot["results"] = []
            snapshot["current_feed"] = None
            snapshot["total_items_seen"] = int(payload.get("total_items_seen") or 0)
            snapshot["total_new_entries"] = int(payload.get("total_new_entries") or 0)
            snapshot["pruned_entries"] = 0

        _mutate_pipeline_progress(apply)
        return

    if event == "feed_started":
        def apply(snapshot: dict) -> None:
            snapshot["stage"] = "compile_feed"
            snapshot["stage_label"] = "Refreshing feeds"
            snapshot["current_feed"] = payload.get("feed")
            snapshot["completed_feeds"] = int(payload.get("completed_feeds") or 0)
            snapshot["total_feeds"] = int(payload.get("total_feeds") or 0)
            snapshot["total_items_seen"] = int(payload.get("total_items_seen") or 0)
            snapshot["total_new_entries"] = int(payload.get("total_new_entries") or 0)
            snapshot["message"] = _refresh_message(snapshot)

        _mutate_pipeline_progress(apply)
        return

    if event == "feed_finished":
        def apply(snapshot: dict) -> None:
            snapshot["stage"] = "compile_feed"
            snapshot["stage_label"] = "Refreshing feeds"
            snapshot["current_feed"] = None
            snapshot["completed_feeds"] = int(payload.get("completed_feeds") or 0)
            snapshot["total_feeds"] = int(payload.get("total_feeds") or 0)
            snapshot["total_items_seen"] = int(payload.get("total_items_seen") or 0)
            snapshot["total_new_entries"] = int(payload.get("total_new_entries") or 0)
            snapshot["results"].append(payload.get("feed") or {})
            snapshot["message"] = _refresh_message(snapshot)

        _mutate_pipeline_progress(apply)
        return

    if event == "done":
        def apply(snapshot: dict) -> None:
            snapshot["stage"] = "compile_feed"
            snapshot["stage_label"] = "Feeds refreshed"
            snapshot["completed_feeds"] = int(payload.get("completed_feeds") or 0)
            snapshot["total_feeds"] = int(payload.get("total_feeds") or 0)
            snapshot["total_items_seen"] = int(payload.get("total_items_seen") or 0)
            snapshot["total_new_entries"] = int(payload.get("total_new_entries") or 0)
            snapshot["pruned_entries"] = int(payload.get("pruned_entries") or 0)
            snapshot["results"] = list(payload.get("results") or [])
            snapshot["current_feed"] = None
            snapshot["message"] = (
                f"Fetched {snapshot['completed_feeds']}/{snapshot['total_feeds']} feeds, "
                f"stored {snapshot['total_new_entries']} new entries."
            )

        _mutate_pipeline_progress(apply)


def _set_pipeline_stage(stage: str, stage_label: str, message: str) -> None:
    def apply(snapshot: dict) -> None:
        snapshot["stage"] = stage
        snapshot["stage_label"] = stage_label
        snapshot["current_feed"] = None
        snapshot["message"] = message

    _mutate_pipeline_progress(apply)


def _finish_pipeline_progress(final_status: str) -> None:
    def apply(snapshot: dict) -> None:
        snapshot["running"] = False
        snapshot["stage"] = "complete" if final_status == "success" else "error"
        snapshot["stage_label"] = "Refresh complete" if final_status == "success" else "Refresh completed with issues"
        snapshot["current_feed"] = None
        snapshot["message"] = _refresh_message(snapshot)

    _mutate_pipeline_progress(apply)


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
    """Run the lightweight refresh pipeline.

    Silently skips if a run is already in progress (prevents OOM from
    concurrent heavy stage runs on the Pi).
    """
    global _pipeline_running
    if not _pipeline_lock.acquire(blocking=False):
        logger.info("Pipeline already running — skipping concurrent start.")
        return
    _pipeline_running = True
    _initialize_pipeline_progress()
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

    Streamlined for the Pi: fetch feeds, apply lightweight quality scoring,
    then apply heuristic theme labels.
    """
    logger.info("Pipeline starting (minimal mode).")
    had_error = False

    try:
        from myrssfeed.scripts.compile_feed import run_compile_feed
    except Exception:
        had_error = True
        logger.exception("Pipeline stage compile_feed failed to load.")
    else:
        try:
            run_compile_feed(progress_cb=_handle_compile_progress)
        except Exception:
            had_error = True
            logger.exception("Pipeline stage %s failed — continuing with remaining stages.", "compile_feed")

    try:
        from myrssfeed.scripts.quality_score import run_quality_score
    except Exception:
        had_error = True
        logger.exception("Pipeline stage quality_score failed to load.")
    else:
        _set_pipeline_stage("quality_score", "Scoring articles", "Scoring article quality…")
        try:
            quality_updates = int(run_quality_score() or 0)

            def apply(snapshot: dict) -> None:
                snapshot["quality_updates"] = quality_updates

            _mutate_pipeline_progress(apply)
        except Exception:
            had_error = True
            logger.exception("Pipeline stage %s failed — continuing with remaining stages.", "quality_score")

    try:
        from myrssfeed.scripts.theme_labeling import run_theme_labeling
    except Exception:
        had_error = True
        logger.exception("Pipeline stage theme_labeling failed to load.")
    else:
        _set_pipeline_stage("theme_labeling", "Applying theme labels", "Applying theme labels…")
        try:
            theme_updates = int(run_theme_labeling() or 0)

            def apply(snapshot: dict) -> None:
                snapshot["theme_updates"] = theme_updates
                snapshot["message"] = (
                    f"Fetched {snapshot.get('completed_feeds', 0)}/{snapshot.get('total_feeds', 0)} feeds, "
                    f"stored {snapshot.get('total_new_entries', 0)} new entries."
                )

            _mutate_pipeline_progress(apply)
        except Exception:
            had_error = True
            logger.exception("Pipeline stage %s failed — continuing with remaining stages.", "theme_labeling")

    final_status = "error" if had_error else "success"
    _record_pipeline_status(final_status)
    _finish_pipeline_progress(final_status)
    logger.info("Pipeline complete with status %s.", final_status)


def _get_persisted_setting(key: str) -> Optional[str]:
    conn = get_db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row["value"] if row else None


def _minutes_since_iso_timestamp(ts: Optional[str]) -> Optional[int]:
    """Convert an ISO8601 timestamp string to minutes-since, if parseable."""
    if not ts:
        return None
    try:
        last_dt = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        diff = now - last_dt
        return max(0, int(diff.total_seconds() // 60))
    except Exception:
        return None


def pipeline_refresh_due_on_startup() -> bool:
    """Whether the pipeline should run immediately after service startup.

    We use the persisted `pipeline_last_success_ts` as the "last refresh" time
    indicator. If it's missing/unparseable or older than the configured refresh
    interval, we consider the refresh due.
    """
    minutes = _parse_pipeline_refresh_minutes()
    if minutes <= 0:
        return False

    minutes_since_last_success = _minutes_since_iso_timestamp(
        _get_persisted_setting("pipeline_last_success_ts")
    )
    if minutes_since_last_success is None:
        return True
    return minutes_since_last_success >= minutes


def trigger_pipeline_refresh_if_due_on_startup() -> bool:
    """Start the pipeline if the refresh interval has been exceeded."""
    if is_pipeline_running():
        return False
    if not pipeline_refresh_due_on_startup():
        return False
    return run_pipeline_async()


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


def _parse_newsletter_poll_minutes() -> int:
    raw = _get_persisted_setting("newsletter_poll_minutes")
    if raw is None:
        raw = get_setting("newsletter_poll_minutes") or "30"
    try:
        return max(5, min(1440, int(raw)))
    except (TypeError, ValueError):
        return 30


def _newsletter_poll_enabled() -> bool:
    raw = get_setting("newsletter_enabled") or "false"
    return str(raw).strip().lower() == "true"


def _add_newsletter_job(scheduler: BackgroundScheduler) -> None:
    if not _newsletter_poll_enabled():
        logger.info("Scheduler: newsletter polling disabled via settings.")
        return

    try:
        from myrssfeed.scripts.newsletter_ingest import run_newsletter_ingest
    except Exception:
        logger.exception("Scheduler: newsletter ingest failed to load.")
        return

    minutes = _parse_newsletter_poll_minutes()
    trigger = IntervalTrigger(minutes=minutes)
    name = f"Automatic newsletter poll every {minutes} minutes"

    scheduler.add_job(
        run_newsletter_ingest,
        trigger=trigger,
        kwargs={"require_enabled": True},
        id="newsletter_poll",
        name=name,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler configured: %s.", name)


def create_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler()
    _add_pipeline_job(scheduler)
    _add_newsletter_job(scheduler)
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
