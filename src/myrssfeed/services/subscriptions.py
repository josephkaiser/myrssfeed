import logging
import sqlite3
import threading
from typing import Callable, Optional


logger = logging.getLogger(__name__)

_pending_subscription_lock = threading.Lock()
_pending_subscription_targets: dict[int, bool] = {}


def _normalize_feed_id(feed_id: object) -> Optional[int]:
    try:
        normalized = int(feed_id)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def queue_subscription_change(feed_id: int, subscribed: bool) -> None:
    normalized = _normalize_feed_id(feed_id)
    if normalized is None:
        return
    with _pending_subscription_lock:
        _pending_subscription_targets[normalized] = bool(subscribed)


def clear_pending_subscription_change(feed_id: int) -> None:
    normalized = _normalize_feed_id(feed_id)
    if normalized is None:
        return
    with _pending_subscription_lock:
        _pending_subscription_targets.pop(normalized, None)


def get_pending_subscription_changes() -> dict[int, bool]:
    with _pending_subscription_lock:
        return dict(_pending_subscription_targets)


def effective_subscribed(feed_id: object, subscribed: object) -> bool:
    normalized = _normalize_feed_id(feed_id)
    default_value = bool(subscribed)
    if normalized is None:
        return default_value
    with _pending_subscription_lock:
        pending = _pending_subscription_targets.get(normalized)
    if pending is None:
        return default_value
    return pending


def apply_effective_subscription(row: dict) -> dict:
    next_row = dict(row)
    next_row["subscribed"] = effective_subscribed(
        next_row.get("id"),
        next_row.get("subscribed", 1),
    )
    return next_row


def filter_subscribed_rows(rows: list[dict]) -> list[dict]:
    filtered: list[dict] = []
    for row in rows:
        next_row = apply_effective_subscription(row)
        if next_row.get("subscribed"):
            filtered.append(next_row)
    return filtered


def apply_pending_subscription_changes(
    get_db: Callable[[], sqlite3.Connection],
) -> list[dict]:
    with _pending_subscription_lock:
        if not _pending_subscription_targets:
            return []
        pending = dict(_pending_subscription_targets)
        _pending_subscription_targets.clear()

    conn = get_db()
    try:
        conn.execute("BEGIN")
        for feed_id, subscribed in pending.items():
            conn.execute(
                "UPDATE feeds SET subscribed = ? WHERE id = ?",
                (1 if subscribed else 0, feed_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        with _pending_subscription_lock:
            _pending_subscription_targets.update(pending)
        logger.exception("Could not apply queued subscription changes.")
        return []
    finally:
        conn.close()

    return [
        {"feed_id": feed_id, "subscribed": subscribed}
        for feed_id, subscribed in sorted(pending.items())
    ]


def reset_pending_subscription_changes() -> None:
    with _pending_subscription_lock:
        _pending_subscription_targets.clear()
