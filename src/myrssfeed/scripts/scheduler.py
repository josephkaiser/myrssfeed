import copy
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from myrssfeed.services.subscriptions import apply_pending_subscription_changes
from myrssfeed.utils.helpers import get_db, set_setting, get_setting

logger = logging.getLogger(__name__)

_pipeline_lock = threading.Lock()
_pipeline_progress_lock = threading.Lock()
_pipeline_running = False
_scheduler: Optional[BackgroundScheduler] = None

PIPELINE_CONTINUOUS_INTERVAL_SECONDS = 30
PIPELINE_SCHEDULE_DEFAULT = "15m"
PIPELINE_SCHEDULE_DAY_DEFAULT = "monday"
PIPELINE_SCHEDULE_TIME_DEFAULT = "06:00"
PIPELINE_INTERVAL_OPTION_TO_MINUTES: dict[str, int] = {
    "15m": 15,
    "30m": 30,
    "45m": 45,
    "1h": 60,
    "2h": 120,
    "12h": 720,
    "1d": 1440,
}
PIPELINE_WEEKDAY_TO_CRON: dict[str, str] = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}
PIPELINE_SCHEDULE_LABELS: dict[str, str] = {
    "continuous": "Continuous refresh",
    "15m": "Refresh every 15 minutes",
    "30m": "Refresh every 30 minutes",
    "45m": "Refresh every 45 minutes",
    "1h": "Refresh every hour",
    "2h": "Refresh every 2 hours",
    "12h": "Refresh every 12 hours",
    "1d": "Daily refresh",
    "weekly": "Weekly refresh",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_pipeline_schedule_option(raw: Optional[str]) -> str:
    value = str(raw or "").strip().lower()
    aliases = {
        "15": "15m",
        "30": "30m",
        "45": "45m",
        "60": "1h",
        "120": "2h",
        "720": "12h",
        "1440": "1d",
        "daily": "1d",
    }
    normalized = aliases.get(value, value)
    if normalized in PIPELINE_SCHEDULE_LABELS:
        return normalized
    return PIPELINE_SCHEDULE_DEFAULT


def normalize_pipeline_schedule_day(raw: Optional[str]) -> str:
    value = str(raw or "").strip().lower()
    aliases = {
        "mon": "monday",
        "tue": "tuesday",
        "wed": "wednesday",
        "thu": "thursday",
        "fri": "friday",
        "sat": "saturday",
        "sun": "sunday",
    }
    normalized = aliases.get(value, value)
    if normalized in PIPELINE_WEEKDAY_TO_CRON:
        return normalized
    return PIPELINE_SCHEDULE_DAY_DEFAULT


def normalize_pipeline_schedule_time(raw: Optional[str]) -> str:
    value = str(raw or "").strip()
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
    if match:
        return value
    return PIPELINE_SCHEDULE_TIME_DEFAULT


def pipeline_schedule_minutes_fallback(schedule: str) -> int:
    normalized = normalize_pipeline_schedule_option(schedule)
    if normalized == "continuous":
        return 0
    if normalized == "weekly":
        return 7 * 24 * 60
    return PIPELINE_INTERVAL_OPTION_TO_MINUTES.get(normalized, 15)


def _closest_schedule_option_for_minutes(minutes: int) -> str:
    options = list(PIPELINE_INTERVAL_OPTION_TO_MINUTES.items())
    option, _ = min(options, key=lambda item: (abs(item[1] - minutes), item[1]))
    return option


def _schedule_option_from_legacy(minutes_raw: Optional[str], legacy_freq: str) -> str:
    if legacy_freq == "daily":
        return "1d"
    if legacy_freq == "hourly":
        return "1h"
    if legacy_freq == "10m":
        return "15m"

    if minutes_raw is not None:
        try:
            minutes = int(minutes_raw)
        except (TypeError, ValueError):
            return PIPELINE_SCHEDULE_DEFAULT
        if minutes <= 0:
            return "continuous"
        return _closest_schedule_option_for_minutes(minutes)

    default_minutes = get_setting("pipeline_refresh_minutes") or "15"
    try:
        return _closest_schedule_option_for_minutes(int(default_minutes))
    except (TypeError, ValueError):
        return PIPELINE_SCHEDULE_DEFAULT


def get_pipeline_schedule_settings() -> dict[str, str]:
    schedule_raw = _get_persisted_setting("pipeline_refresh_schedule")
    day_raw = _get_persisted_setting("pipeline_refresh_day")
    time_raw = _get_persisted_setting("pipeline_refresh_time")

    if schedule_raw is None:
        schedule = _schedule_option_from_legacy(
            _get_persisted_setting("pipeline_refresh_minutes"),
            (_get_persisted_setting("pipeline_schedule_frequency") or "").strip().lower(),
        )
    else:
        schedule = normalize_pipeline_schedule_option(schedule_raw)

    if time_raw is None:
        time_raw = _get_persisted_setting("pipeline_schedule_time")

    return {
        "pipeline_refresh_schedule": schedule,
        "pipeline_refresh_day": normalize_pipeline_schedule_day(day_raw),
        "pipeline_refresh_time": normalize_pipeline_schedule_time(time_raw),
    }


def _parse_pipeline_time_parts(raw: str) -> tuple[int, int]:
    value = normalize_pipeline_schedule_time(raw)
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text), int(minute_text)


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_pipeline_schedule() -> dict:
    persisted_schedule = _get_persisted_setting("pipeline_refresh_schedule")
    legacy_freq = (_get_persisted_setting("pipeline_schedule_frequency") or "").strip().lower()
    if persisted_schedule is None and legacy_freq == "off":
        return {
            "kind": "disabled",
            "name": "Automatic refresh disabled",
        }

    settings = get_pipeline_schedule_settings()
    schedule = settings["pipeline_refresh_schedule"]
    if schedule == "continuous":
        return {
            "kind": "continuous",
            "seconds": PIPELINE_CONTINUOUS_INTERVAL_SECONDS,
            "name": PIPELINE_SCHEDULE_LABELS["continuous"],
        }

    if schedule == "weekly":
        hour, minute = _parse_pipeline_time_parts(settings["pipeline_refresh_time"])
        day = settings["pipeline_refresh_day"]
        return {
            "kind": "weekly",
            "weekday": day,
            "cron_weekday": PIPELINE_WEEKDAY_TO_CRON[day],
            "hour": hour,
            "minute": minute,
            "time": settings["pipeline_refresh_time"],
            "name": f"Weekly refresh every {day.capitalize()} at {settings['pipeline_refresh_time']}",
        }

    if schedule == "1d":
        hour, minute = _parse_pipeline_time_parts(settings["pipeline_refresh_time"])
        return {
            "kind": "daily",
            "hour": hour,
            "minute": minute,
            "time": settings["pipeline_refresh_time"],
            "name": f"Daily refresh at {settings['pipeline_refresh_time']}",
        }

    minutes = PIPELINE_INTERVAL_OPTION_TO_MINUTES.get(schedule, 15)
    return {
        "kind": "interval",
        "minutes": minutes,
        "name": PIPELINE_SCHEDULE_LABELS.get(schedule, f"Refresh every {minutes} minutes"),
    }


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
        try:
            applied = apply_pending_subscription_changes(get_db)
            if applied:
                logger.info("Applied %d queued subscription change(s) after refresh.", len(applied))
        except Exception:
            logger.exception("Could not apply queued subscription changes after refresh.")
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
    schedule = _parse_pipeline_schedule()
    kind = schedule.get("kind")
    if kind == "disabled":
        return False
    if kind == "continuous":
        return True

    last_success_raw = _get_persisted_setting("pipeline_last_success_ts")
    if not last_success_raw:
        return True
    try:
        last_success = datetime.fromisoformat(last_success_raw)
    except Exception:
        return True
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)

    if kind == "interval":
        minutes = int(schedule.get("minutes") or 0)
        if minutes <= 0:
            return False
        now = datetime.now(timezone.utc)
        diff = now - last_success.astimezone(timezone.utc)
        return diff.total_seconds() >= minutes * 60

    local_tz = _local_timezone()
    now_local = datetime.now(local_tz)
    last_success_local = last_success.astimezone(local_tz)

    if kind == "daily":
        scheduled_at = now_local.replace(
            hour=int(schedule.get("hour") or 0),
            minute=int(schedule.get("minute") or 0),
            second=0,
            microsecond=0,
        )
        if scheduled_at > now_local:
            scheduled_at -= timedelta(days=1)
        return last_success_local < scheduled_at

    if kind == "weekly":
        target_day = list(PIPELINE_WEEKDAY_TO_CRON.keys()).index(str(schedule.get("weekday") or "monday"))
        scheduled_at = now_local.replace(
            hour=int(schedule.get("hour") or 0),
            minute=int(schedule.get("minute") or 0),
            second=0,
            microsecond=0,
        )
        days_back = (now_local.weekday() - target_day) % 7
        scheduled_at -= timedelta(days=days_back)
        if scheduled_at > now_local:
            scheduled_at -= timedelta(days=7)
        return last_success_local < scheduled_at

    return False


def trigger_pipeline_refresh_if_due_on_startup() -> bool:
    """Start the pipeline if the refresh interval has been exceeded."""
    if is_pipeline_running():
        return False
    if not pipeline_refresh_due_on_startup():
        return False
    return run_pipeline_async()


def _parse_pipeline_refresh_minutes() -> int:
    """Return the current schedule as a nominal minute count.

    This remains for compatibility with older code/tests. New schedule-aware
    behavior should use `_parse_pipeline_schedule()` instead.
    """
    legacy_freq = (_get_persisted_setting("pipeline_schedule_frequency") or "").strip().lower()
    if legacy_freq == "off":
        return 0
    settings = get_pipeline_schedule_settings()
    return pipeline_schedule_minutes_fallback(settings["pipeline_refresh_schedule"])


def _add_pipeline_job(scheduler: BackgroundScheduler) -> None:
    schedule = _parse_pipeline_schedule()
    kind = schedule.get("kind")
    if kind == "disabled":
        logger.info("Scheduler: automatic refresh disabled via settings.")
        return

    if kind == "continuous":
        trigger = IntervalTrigger(seconds=int(schedule.get("seconds") or PIPELINE_CONTINUOUS_INTERVAL_SECONDS))
    elif kind == "interval":
        trigger = IntervalTrigger(minutes=int(schedule.get("minutes") or 15))
    elif kind == "daily":
        trigger = CronTrigger(
            hour=int(schedule.get("hour") or 0),
            minute=int(schedule.get("minute") or 0),
            timezone=_local_timezone(),
        )
    else:
        trigger = CronTrigger(
            day_of_week=str(schedule.get("cron_weekday") or "mon"),
            hour=int(schedule.get("hour") or 0),
            minute=int(schedule.get("minute") or 0),
            timezone=_local_timezone(),
        )
    name = str(schedule.get("name") or "Automatic refresh")

    scheduler.add_job(
        run_pipeline,
        trigger=trigger,
        id="pipeline_refresh",
        name=name,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
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
