import logging
import logging.handlers
import hashlib
import os
import json
import random
import re
import sqlite3
import threading
import urllib.parse
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from collections import deque
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from typing import Any, Optional, Union

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from scripts.scheduler import (
    create_scheduler,
    run_pipeline_async,
    is_pipeline_running,
    reconfigure_scheduler,
    trigger_pipeline_refresh_if_due_on_startup,
)
from scripts.newsletter_ingest import is_newsletter_running, run_newsletter_ingest_async
from utils.helpers import (
    DEFAULTS as CORE_DEFAULTS,
    DB_FILE as CORE_DB_FILE,
    get_db as core_get_db,
    get_setting as core_get_setting,
    init_db as core_init_db,
    set_setting as core_set_setting,
)
import utils.helpers as core_helpers


# ── Logging ───────────────────────────────────────────────────────────────────

_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(_LOG_DIR, "myrssfeed.log")

_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)
_fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5)
_fh.setFormatter(_fmt)
_root.addHandler(_fh)

logger = logging.getLogger(__name__)


# ── Database / settings (delegating to utils.helpers) ──────────────────────────

# Reuse the shared helpers module for DB access and settings so the web app and
# pipeline scripts always agree on schema and defaults.
DEFAULTS: dict[str, str] = CORE_DEFAULTS
DB_FILE: str = CORE_DB_FILE  # exposed for tests/debugging

# Sort options for entry listing (must be defined before _fetch_ranked_entries).
SORT_CHRONOLOGICAL = "chronological"
SORT_QUALITY_DESC = "quality_desc"
SORT_QUALITY_ASC = "quality_asc"
SORT_OPTIONS = (SORT_CHRONOLOGICAL, SORT_QUALITY_DESC, SORT_QUALITY_ASC)


def get_db() -> sqlite3.Connection:
    """Compatibility wrapper for tests and callers that imported main.get_db."""
    core_helpers.DB_FILE = DB_FILE
    return core_get_db()


def init_db() -> None:
    """Initialize the core schema and then seed the local feed catalogue."""
    core_helpers.DB_FILE = DB_FILE
    core_init_db()
    conn = core_get_db()
    try:
        _seed_catalogue_feeds(conn)
    finally:
        conn.close()


def get_setting(key: str) -> str:
    return core_get_setting(key)


def set_setting(key: str, value: str) -> None:
    core_set_setting(key, value)


# ── Schemas ───────────────────────────────────────────────────────────────────

class FeedCreate(BaseModel):
    url: HttpUrl
    title: Optional[str] = None


class FeedOut(BaseModel):
    id: int
    url: str
    title: Optional[str]
    color: Optional[str] = None
    subscribed: Optional[bool] = None
    entry_count: Optional[int] = None


class FeedUpdate(BaseModel):
    title: Optional[str] = None
    color: Optional[str] = None
    subscribed: Optional[bool] = None


class EntryOut(BaseModel):
    id: int
    feed_id: int
    feed_title: Optional[str]
    feed_domain: Optional[str] = None  # for favicon in lazy-loaded cards
    title: Optional[str]
    link: Optional[str]
    published: Optional[str]
    summary: Optional[str]
    read: int = 0
    liked: int = 0
    thumbnail_url: Optional[str] = None
    assessment_label: Optional[str] = None
    assessment_label_color: Optional[str] = None
    theme_label: Optional[str] = None
    theme_label_color: Optional[str] = None


class EntryVoteUpdate(BaseModel):
    liked: bool


class SettingsUpdate(BaseModel):
    retention_days: Optional[str] = None
    theme: Optional[str] = None
    max_entries: Optional[str] = None
    pipeline_refresh_minutes: Optional[str] = None
    newsletter_enabled: Optional[str] = None
    newsletter_imap_host: Optional[str] = None
    newsletter_imap_port: Optional[str] = None
    newsletter_imap_username: Optional[str] = None
    newsletter_imap_password: Optional[str] = None
    newsletter_imap_folder: Optional[str] = None
    newsletter_poll_minutes: Optional[str] = None


class DetectRequest(BaseModel):
    url: str


# Used by the Discover "remove from catalogue" button.
# Removes the feed from the user catalogue (so it disappears from Discover)
# and unsubscribes it (so it disappears from subscriptions lists).
class CatalogRemoveRequest(BaseModel):
    url: str


# ── Catalog ───────────────────────────────────────────────────────────────────

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "data", "feed_catalog.json")
try:
    with open(_CATALOG_PATH, "r", encoding="utf-8") as _f:
        _FEED_CATALOG = json.load(_f)
except Exception:
    _FEED_CATALOG = []

_STATIC_CATALOG_URLS = {f["url"] for f in _FEED_CATALOG}
RANDOM_SEED_COOKIE = "myrssfeed_random_seed"
WALK_STATE_COOKIE = "myrssfeed_walk_state"
WALK_CANDIDATE_LIMIT = 500
WALK_INITIAL_STRENGTH = 1.0
WALK_DECAY_FACTOR = 0.7
WALK_MIN_STRENGTH = 0.15
_WALK_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_WALK_STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "new",
    "not",
    "of",
    "on",
    "or",
    "our",
    "out",
    "over",
    "so",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "to",
    "under",
    "up",
    "was",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}


def _seed_catalogue_feeds(conn: sqlite3.Connection) -> None:
    """Ensure all feeds from the static catalogue exist in the DB with subscribed=0.
    New rows are catalogue-only (for training/surfacing); user can subscribe later.
    """
    if not _FEED_CATALOG:
        return
    for item in _FEED_CATALOG:
        url = item.get("url") or ""
        name = (item.get("name") or url).strip()
        category = (item.get("category") or "").strip() or None
        if not url:
            continue
        try:
            conn.execute(
                """
                INSERT INTO feeds (url, title, subscribed, category)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(url) DO NOTHING
                """,
                (url, name or None, category),
            )
        except Exception:
            # Ignore duplicate or schema mismatch (e.g. older DB without category)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO feeds (url, title, subscribed) VALUES (?, ?, 0)",
                    (url, name or None),
                )
            except Exception:
                pass
    conn.commit()


def _add_to_user_catalog(url: str, name: str) -> None:
    """Persist a feed in the user catalog so it appears on the discover page."""
    if url in _STATIC_CATALOG_URLS:
        return
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO user_catalog (url, name) VALUES (?, ?)",
        (url, name or url),
    )
    conn.commit()
    conn.close()


def _get_full_catalog() -> list[dict]:
    """Merge the static catalog with user-added entries."""
    conn = get_db()
    rows = conn.execute("SELECT url, name, category, description FROM user_catalog").fetchall()
    conn.close()
    static_urls = _STATIC_CATALOG_URLS
    static_items = [{**item, "removable": False} for item in _FEED_CATALOG]
    extras = [
        {
            "url": r["url"],
            "name": r["name"],
            "category": r["category"],
            "description": r["description"],
            "removable": True,
        }
        for r in rows
        if r["url"] not in static_urls
    ]
    return static_items + extras


def _random_seed_from_request(request: Request) -> Optional[int]:
    """Read the persisted random-order seed from a cookie."""
    raw = request.cookies.get(RANDOM_SEED_COOKIE, "")
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return abs(int(raw))
    except (TypeError, ValueError):
        return None


def _random_enabled_from_request(request: Request) -> bool:
    return _random_seed_from_request(request) is not None


def _normalize_walk_direction(value: Optional[Union[int, str]]) -> Optional[int]:
    try:
        direction = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if direction > 0:
        return 1
    if direction < 0:
        return -1
    return None


def _normalize_walk_strength(value: Optional[Union[int, float, str]]) -> Optional[float]:
    try:
        strength = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if strength != strength:
        return None
    return max(0.0, min(1.0, strength))


def _parse_int(value: Optional[Union[int, str]]) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_int_list(value: Optional[str]) -> set[int]:
    if not value:
        return set()
    ids: set[int] = set()
    for part in re.split(r"[,\s]+", str(value).strip()):
        if not part:
            continue
        try:
            ids.add(int(part))
        except (TypeError, ValueError):
            continue
    return ids


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


def _walk_tokens(row: dict) -> set[str]:
    parts = [
        row.get("title") or "",
        row.get("summary") or "",
        row.get("feed_title") or "",
    ]
    tokens: set[str] = set()
    for part in parts:
        for token in _WALK_TOKEN_RE.findall(str(part).lower()):
            if len(token) < 3 or token in _WALK_STOPWORDS:
                continue
            tokens.add(token)
    return tokens


def _walk_similarity(anchor_tokens: set[str], candidate_tokens: set[str]) -> float:
    if not anchor_tokens or not candidate_tokens:
        return 0.0
    overlap = len(anchor_tokens & candidate_tokens)
    if not overlap:
        return 0.0
    return overlap / max(len(anchor_tokens), 1)


def _read_walk_state(
    request: Request,
    walk_anchor_id: Optional[int] = None,
    walk_direction: Optional[int] = None,
) -> tuple[Optional[int], Optional[int], float]:
    anchor_id = _parse_int(walk_anchor_id)
    direction = _normalize_walk_direction(walk_direction)
    strength = WALK_INITIAL_STRENGTH if anchor_id is not None and direction is not None else 0.0

    if anchor_id is not None and direction is not None:
        return anchor_id, direction, strength

    raw = request.cookies.get(WALK_STATE_COOKIE, "")
    if not raw:
        return anchor_id, direction, strength

    try:
        data = json.loads(raw)
    except Exception:
        return anchor_id, direction, strength

    if anchor_id is None:
        anchor_id = _parse_int(data.get("anchor_id"))
    if direction is None:
        direction = _normalize_walk_direction(data.get("direction"))
    cookie_strength = _normalize_walk_strength(data.get("strength"))
    if cookie_strength is not None:
        strength = cookie_strength
    elif anchor_id is not None and direction is not None:
        strength = WALK_INITIAL_STRENGTH
    return anchor_id, direction, strength


def _set_walk_state_cookie(
    response: Any,
    anchor_id: int,
    direction: int,
    strength: float = WALK_INITIAL_STRENGTH,
) -> None:
    normalized_strength = _normalize_walk_strength(strength)
    if normalized_strength is None:
        normalized_strength = WALK_INITIAL_STRENGTH
    if normalized_strength < WALK_MIN_STRENGTH:
        response.delete_cookie(WALK_STATE_COOKIE, path="/")
        return
    response.set_cookie(
        WALK_STATE_COOKIE,
        json.dumps(
            {"anchor_id": int(anchor_id), "direction": int(direction), "strength": normalized_strength},
            separators=(",", ":"),
        ),
        httponly=True,
        samesite="lax",
        path="/",
    )


def _pick_walk_candidate(
    rows: list[dict],
    anchor_row: dict,
    direction: int,
    strength: float,
) -> Optional[dict]:
    if not rows or not anchor_row:
        return None

    anchor_id = int(anchor_row.get("id") or 0)
    anchor_tokens = _walk_tokens(anchor_row)
    if not anchor_id or not anchor_tokens:
        return None

    walk_strength = _normalize_walk_strength(strength) or 0.0
    if walk_strength < WALK_MIN_STRENGTH:
        return None

    anchor_feed_id = int(anchor_row.get("feed_id") or 0)
    ranked: list[tuple[float, float, int, dict]] = []
    total = len(rows)
    if total <= 1:
        return None

    for idx, row in enumerate(rows):
        row_id = int(row.get("id") or 0)
        if not row_id or row_id == anchor_id:
            continue

        candidate_tokens = _walk_tokens(row)
        similarity = _walk_similarity(anchor_tokens, candidate_tokens)
        recency_weight = (total - idx) / total
        score = float(row.get("score") or 0.0)
        same_feed_bonus = (0.06 + 0.04 * walk_strength) if int(row.get("feed_id") or 0) == anchor_feed_id else 0.0
        directional_weight = 0.42 + (0.36 * walk_strength)
        recency_bias = 0.18 + (0.08 * walk_strength)
        score_bias = 0.12 + (0.08 * walk_strength)

        if direction > 0:
            blended = (directional_weight * similarity) + (recency_bias * recency_weight) + (score_bias * score) + same_feed_bonus
        else:
            blended = (
                (directional_weight * (1.0 - similarity))
                + (recency_bias * recency_weight)
                + (score_bias * (1.0 - score))
                - same_feed_bonus
            )

        ranked.append((blended, similarity, -idx, row))

    if not ranked:
        return None

    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    top_n = min(max(6, int(10 * walk_strength) + 4), len(ranked))
    pool = ranked[:top_n]
    weights = [top_n - i for i in range(top_n)]
    return random.choices(pool, weights=weights, k=1)[0][3]


def _ranking_expr(
    random_seed: Optional[int],
    score_weight: float = 0.6,
    quality_weight: float = 0.3,
    random_weight: float = 0.1,
) -> str:
    """Build a SQL ranking expression with optional deterministic randomness."""
    expr = f"(COALESCE(e.score,0)*{score_weight} + COALESCE(e.quality_score,0)*{quality_weight}"
    if random_seed is not None:
        seed = abs(int(random_seed))
        expr += (
            " + ("
            f"abs((COALESCE(e.id, 0) * 1103515245 + COALESCE(e.feed_id, 0) * 12345 + {seed}) % 2147483647)"
            " / 2147483647.0)"
            f" * {random_weight}"
        )
    expr += ")"
    return expr


def _build_entry_filters(
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
) -> tuple[list[str], list]:
    filters: list[str] = []
    params: list = []

    scope_clause, scope_params = _source_scope_clause(source_scope)
    filters.append(scope_clause)
    params.extend(scope_params)

    if q and q.strip():
        query_text = q.strip()
        filters.append("(e.title LIKE ? OR e.summary LIKE ?)")
        params += [f"%{query_text}%", f"%{query_text}%"]
    if feed_id is not None and source_scope == SOURCE_SCOPE_MY:
        filters.append("e.feed_id = ?")
        params.append(feed_id)
    if days_int is not None and days_int in DATE_RANGE_DAYS:
        filters.append("(e.published IS NOT NULL AND date(e.published) >= date('now', ?))")
        params.append(f"-{days_int} days")

    # Optional quality filter (server-side) to hide low-quality items.
    if quality_level is not None:
        try:
            lvl = int(quality_level)
        except (TypeError, ValueError):
            lvl = 1
        lvl = max(0, min(3, lvl))
        if lvl == 0:
            min_title, min_summary = 5, 20
        elif lvl == 1:
            min_title, min_summary = 10, 40
        elif lvl == 2:
            min_title, min_summary = 20, 80
        else:
            min_title, min_summary = 30, 120

        # Map UI aggressiveness levels to quality_score cutoffs.
        # We keep a length-based fallback for safety when a DB hasn't been
        # scored yet (quality_score may still be the default 0.0).
        quality_threshold = {0: 0.25, 1: 0.35, 2: 0.5, 3: 0.65}.get(lvl, 0.35)
        filters.append(
            "("
            "e.link IS NOT NULL AND TRIM(e.link) != '' AND ("
            "COALESCE(e.quality_score, 0) >= ? OR "
            "LENGTH(COALESCE(e.title, '')) >= ? OR "
            "LENGTH(COALESCE(e.summary, '')) >= ?"
            ")"
            ")"
        )
        params.extend([quality_threshold, min_title, min_summary])

    # Optional theme filter: restrict results to selected theme labels.
    # If theme_labels is None -> include all (no filter).
    if theme_labels is not None:
        if theme_labels:
            placeholders = ", ".join("?" for _ in theme_labels)
            # Treat unlabeled entries as "World News" so the filter doesn't
            # go completely empty before the first theme labeling run.
            filters.append(f"COALESCE(e.theme_label, 'World News') IN ({placeholders})")
            params.extend(list(theme_labels))
        else:
            # Explicit empty selection: match nothing.
            filters.append("1=0")

    return filters, params


def _finalize_entry_row(row: dict) -> dict:
    """Strip internal ranking fields and derive the feed domain."""
    entry = dict(row)
    feed_url = entry.pop("feed_url", None)
    entry.pop("base_rank", None)
    entry.pop("published_day", None)
    entry.pop("effective_rank", None)
    entry["feed_domain"] = _feed_host(feed_url) or None
    return entry


def _feed_host(feed_url: Optional[str]) -> str:
    parsed = urllib.parse.urlparse(feed_url or "")
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return ""
    host = (parsed.hostname or parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _seeded_noise(seed: Optional[int], row: dict) -> float:
    """Return a stable 0-1 noise value for a row/seed pair."""
    if seed is None:
        return 0.0
    payload = "|".join([
        str(abs(int(seed))),
        str(row.get("id") or ""),
        str(row.get("feed_id") or ""),
        str(row.get("published") or ""),
        str(row.get("title") or ""),
    ]).encode("utf-8", errors="ignore")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def _source_key(row: dict) -> str:
    host = _feed_host(row.get("feed_url"))
    if host:
        return host
    feed_id = int(row.get("feed_id") or 0)
    if feed_id:
        return f"feed:{feed_id}"
    return f"row:{row.get('id', '')}"


def _apply_source_diversity(
    entries: list[dict],
    random_seed: Optional[int] = None,
    recent_window: int = 6,
    repeat_penalty: float = 0.18,
    streak_penalty: float = 0.35,
    novelty_bonus: float = 0.05,
    recency_factor: float = 0.8,
    rank_factor: float = 0.2,
    noise_factor: float = 0.0,
) -> list[dict]:
    """
    Re-rank a base-ordered entry stream so a feed that appears repeatedly
    gets progressively less weight in the next few slots.
    """
    if len(entries) <= 1:
        return [_finalize_entry_row(entries[0])] if entries else []

    n = len(entries)
    pool = []
    for idx, row in enumerate(entries):
        copy = dict(row)
        recency_weight = (n - idx) / n  # 1.0 for newest in the day, down to ~0
        base_rank = float(copy.get("base_rank") or 0.0)
        noise = _seeded_noise(random_seed, copy)
        copy["effective_rank"] = (
            (recency_factor * recency_weight)
            + (rank_factor * base_rank)
            + (noise_factor * noise)
        )
        pool.append((idx, copy))
    ranked: list[dict] = []
    recent = deque()
    recent_counts: dict[str, int] = {}
    last_source: Optional[str] = None
    streak = 0

    while pool:
        source_keys = {_source_key(row) for _, row in pool}
        best_pos = 0
        best_adjusted = None
        best_base = None
        best_original_idx = None

        for pos, (original_idx, row) in enumerate(pool):
            source_key = _source_key(row)
            base_rank = float(row.get("effective_rank") or row.get("base_rank") or 0.0)
            repeat_count = recent_counts.get(source_key, 0)
            adjusted = base_rank - (repeat_penalty * repeat_count)
            if source_key == last_source:
                adjusted -= streak_penalty * streak
            elif repeat_count == 0 and len(source_keys) > 1:
                adjusted += novelty_bonus

            if (
                best_adjusted is None
                or adjusted > best_adjusted
                or (adjusted == best_adjusted and base_rank > (best_base if best_base is not None else float("-inf")))
                or (
                    adjusted == best_adjusted
                    and base_rank == best_base
                    and original_idx < (best_original_idx if best_original_idx is not None else original_idx)
                )
            ):
                best_pos = pos
                best_adjusted = adjusted
                best_base = base_rank
                best_original_idx = original_idx

        _, chosen = pool.pop(best_pos)
        ranked.append(_finalize_entry_row(chosen))

        source_key = _source_key(chosen)
        if source_key:
            recent.append(source_key)
            recent_counts[source_key] = recent_counts.get(source_key, 0) + 1
            if len(recent) > recent_window:
                old = recent.popleft()
                recent_counts[old] -= 1
                if recent_counts[old] <= 0:
                    del recent_counts[old]

        if source_key == last_source:
            streak += 1
        else:
            last_source = source_key
            streak = 1

    return ranked


def _apply_daily_source_diversity(
    entries: list[dict],
    random_seed: Optional[int] = None,
    recency_factor: float = 0.8,
    rank_factor: float = 0.2,
    noise_factor: float = 0.0,
) -> list[dict]:
    """Keep articles grouped by day, then diversify sources within each day."""
    if not entries:
        return []

    ranked: list[dict] = []
    day_groups: list[list[dict]] = []
    current_day = None
    current_group: list[dict] = []

    for row in entries:
        day = row.get("published_day")
        if day != current_day and current_group:
            day_groups.append(current_group)
            current_group = []
        current_day = day
        current_group.append(row)

    if current_group:
        day_groups.append(current_group)

    for group in day_groups:
        ranked.extend(
            _apply_source_diversity(
                group,
                random_seed=random_seed,
                recency_factor=recency_factor,
                rank_factor=rank_factor,
                noise_factor=noise_factor,
            )
        )

    return ranked


def _fetch_ranked_entries(
    conn: sqlite3.Connection,
    random_seed: Optional[int],
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
    sort: str = SORT_CHRONOLOGICAL,
) -> list[dict]:
    rank_expr = _ranking_expr(None)
    query = f"""
        SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
               e.title, e.link, e.published, DATE(e.published) AS published_day, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score,
               COALESCE(e.quality_score, 0.0) AS quality_score,
               e.assessment_label,
               e.assessment_label_color,
               e.theme_label,
               e.theme_label_color,
               {rank_expr} AS base_rank
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
    """
    filters, params = _build_entry_filters(q, feed_id, quality_level, days_int, source_scope, theme_labels)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    if sort == SORT_QUALITY_DESC:
        query += " ORDER BY COALESCE(e.quality_score, 0) DESC, (e.published IS NULL), e.published DESC, e.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    if sort == SORT_QUALITY_ASC:
        query += " ORDER BY COALESCE(e.quality_score, 0) ASC, (e.published IS NULL), e.published DESC, e.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    # chronological (default): date + diversity
    query += " ORDER BY (e.published IS NULL), DATE(e.published) DESC, e.published DESC, base_rank DESC"
    rows = conn.execute(query, params).fetchall()
    random_enabled = random_seed is not None
    recency_factor = 0.3 if random_enabled else 0.8
    rank_factor = 0.2 if random_enabled else 0.2
    noise_factor = 0.5 if random_enabled else 0.0
    return _apply_daily_source_diversity(
        [dict(r) for r in rows],
        random_seed=random_seed,
        recency_factor=recency_factor,
        rank_factor=rank_factor,
        noise_factor=noise_factor,
    )


def _article_neighbor_urls(
    conn: sqlite3.Connection,
    entry_id: int,
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
    sort: str = SORT_CHRONOLOGICAL,
) -> tuple[Optional[str], Optional[str]]:
    rows = _fetch_ranked_entries(
        conn, None, q, feed_id, quality_level, days_int, source_scope, theme_labels, sort
    )
    if not rows:
        return None, None

    current_index = next((idx for idx, row in enumerate(rows) if int(row.get("id") or 0) == entry_id), None)
    if current_index is None:
        return None, None

    context_params = {
        "q": q,
        "feed_id": str(feed_id) if feed_id is not None else None,
        "quality_level": str(quality_level) if quality_level is not None else None,
        "days": str(days_int) if days_int is not None else None,
        "scope": source_scope if source_scope != SOURCE_SCOPE_MY else None,
        "themes": ",".join(sorted(theme_labels)) if theme_labels is not None else None,
        "sort": sort if sort != SORT_CHRONOLOGICAL else None,
    }

    prev_url = None
    next_url = None
    if current_index > 0:
        prev_url = _build_url_with_query_params(f"/article/{rows[current_index - 1]['id']}", context_params)
    if current_index + 1 < len(rows):
        next_url = _build_url_with_query_params(f"/article/{rows[current_index + 1]['id']}", context_params)
    return prev_url, next_url


def _fetch_random_entry(
    conn: sqlite3.Connection,
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
    exclude_id: Optional[int] = None,
    exclude_ids: Optional[str] = None,
    walk_anchor_id: Optional[int] = None,
    walk_direction: Optional[int] = None,
    walk_strength: Optional[float] = None,
) -> Optional[dict]:
    """Pick a uniformly random entry while respecting the current filters."""
    filters, params = _build_entry_filters(q, feed_id, quality_level, days_int, source_scope, theme_labels)
    excluded_ids = _parse_int_list(exclude_ids)
    if exclude_id is not None:
        excluded_ids.add(int(exclude_id))
    if excluded_ids:
        excluded_list = sorted(excluded_ids)
        placeholders = ", ".join("?" for _ in excluded_list)
        filters.append(f"e.id NOT IN ({placeholders})")
        params.extend(excluded_list)

    base_query = "FROM entries e JOIN feeds f ON f.id = e.feed_id"
    if filters:
        where_clause = " WHERE " + " AND ".join(filters)
    else:
        where_clause = ""

    total = conn.execute(f"SELECT COUNT(*) {base_query}{where_clause}", params).fetchone()[0]
    if not total:
        return None

    anchor_id = _parse_int(walk_anchor_id)
    direction = _normalize_walk_direction(walk_direction)
    strength = _normalize_walk_strength(walk_strength)
    if strength is None:
        strength = WALK_INITIAL_STRENGTH if anchor_id is not None and direction is not None else 0.0

    if anchor_id is not None and direction is not None:
        anchor_row = conn.execute(
            """
            SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
                   e.title, e.link, e.published, e.summary,
                   e.thumbnail_url,
                   COALESCE(e.read, 0) AS read,
                   COALESCE(e.liked, 0) AS liked,
                   COALESCE(e.score, 0.0) AS score,
                   COALESCE(e.quality_score, 0.0) AS quality_score,
                   e.assessment_label,
                   e.assessment_label_color
            FROM entries e
            JOIN feeds f ON f.id = e.feed_id
            WHERE e.id = ?
            """,
            (anchor_id,),
        ).fetchone()
        if anchor_row:
            walk_rows = conn.execute(
                f"""
                SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
                       e.title, e.link, e.published, e.summary,
                       e.thumbnail_url,
                       COALESCE(e.read, 0) AS read,
                       COALESCE(e.liked, 0) AS liked,
                       COALESCE(e.score, 0.0) AS score,
                       COALESCE(e.quality_score, 0.0) AS quality_score,
                       e.assessment_label,
                       e.assessment_label_color
                {base_query}
                {where_clause}
                ORDER BY (e.published IS NULL), DATE(e.published) DESC, e.published DESC, e.id DESC
                LIMIT ?
                """,
                params + [WALK_CANDIDATE_LIMIT],
            ).fetchall()
            chosen = _pick_walk_candidate([dict(r) for r in walk_rows], dict(anchor_row), direction, strength)
            if chosen:
                return chosen

    offset = random.randrange(total)
    row = conn.execute(
        f"""
        SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score,
               COALESCE(e.quality_score, 0.0) AS quality_score,
               e.assessment_label,
               e.assessment_label_color
        {base_query}
        {where_clause}
        ORDER BY (e.published IS NULL), DATE(e.published) DESC, e.published DESC, e.id DESC
        LIMIT 1 OFFSET ?
        """,
        params + [offset],
    ).fetchone()
    return dict(row) if row else None


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    try:
        if trigger_pipeline_refresh_if_due_on_startup():
            logger.info("Startup: pipeline refresh was due (refresh window exceeded).")
    except Exception:
        # Best-effort only; never fail app startup because of refresh scheduling.
        logger.exception("Startup: refresh due-check failed.")
    logger.info("myRSSfeed started.")
    yield
    scheduler.shutdown(wait=False)
    logger.info("myRSSfeed stopped.")


app = FastAPI(title="myRSSfeed", lifespan=lifespan)

_static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

_templates_dir = os.path.join(os.path.dirname(__file__), "web", "templates")
templates = Jinja2Templates(directory=_templates_dir)


# ── UI routes ─────────────────────────────────────────────────────────────────

# Allowed date-range values for "last X days" filter (None = all-time).
DATE_RANGE_DAYS = (1, 5, 30, 90)
SOURCE_SCOPE_MY = "my"
SOURCE_SCOPE_DISCOVER = "discover"
THEME_LABELS = (
    "Politics",
    "Technology",
    "Business",
    "Stocks",
    "Spam",
    "Science",
    "World News",
)


def _parse_days(days_param: Optional[str]) -> Optional[int]:
    """Parse 'days' query param; empty string or invalid value → None."""
    if days_param is None or days_param.strip() == "":
        return None
    try:
        d = int(days_param)
        return d if d in DATE_RANGE_DAYS else None
    except ValueError:
        return None


def _parse_themes_param(themes_param: Optional[str]) -> Optional[set[str]]:
    """
    Parse a comma-separated `themes` query param into a validated set of theme labels.

    Returns:
      - None: no filter (include all)
      - set(): explicit empty selection (match nothing)
      - set[str]: selected themes
    """
    if themes_param is None:
        return None
    raw = str(themes_param).strip()
    if raw == "":
        return set()
    allowed = {t.lower(): t for t in THEME_LABELS}
    out: set[str] = set()
    # Split on commas only so multi-word labels like "World News" survive.
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        key = p.lower()
        if key in allowed:
            out.add(allowed[key])
    return out


def _normalize_source_scope(scope: Optional[str]) -> str:
    raw = (scope or "").strip().lower()
    if raw == SOURCE_SCOPE_DISCOVER:
        return SOURCE_SCOPE_DISCOVER
    return SOURCE_SCOPE_MY


def _normalize_sort(sort: Optional[str]) -> str:
    raw = (sort or "").strip().lower()
    if raw in SORT_OPTIONS:
        return raw
    return SORT_CHRONOLOGICAL


def _source_scope_clause(source_scope: str) -> tuple[str, list]:
    if source_scope == SOURCE_SCOPE_DISCOVER and _STATIC_CATALOG_URLS:
        urls = sorted(_STATIC_CATALOG_URLS)
        placeholders = ", ".join("?" for _ in urls)
        return f"(COALESCE(f.subscribed, 1) = 1 OR f.url IN ({placeholders}))", urls
    return "(COALESCE(f.subscribed, 1) = 1)", []


def _load_trending(conn: sqlite3.Connection) -> list[dict]:
    """Load a small recency-weighted, source-diverse trending list."""
    trending_query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score,
               e.assessment_label,
               e.assessment_label_color
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        ORDER BY e.published DESC, """
    trending_query += _ranking_expr(None, 0.7, 0.3, 0.0)
    trending_query += " DESC\n        LIMIT 200\n    "
    trending_rows = conn.execute(trending_query).fetchall()
    return _compute_trending([dict(e) for e in trending_rows])


def _build_url_with_query_params(path: str, params: dict[str, Optional[str]]) -> str:
    cleaned = [(key, value) for key, value in params.items() if value not in (None, "")]
    if not cleaned:
        return path
    return f"{path}?{urllib.parse.urlencode(cleaned)}"


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: Optional[str] = None,
    feed_id: Optional[int] = None,
    quality_level: Optional[int] = None,
    days: Optional[str] = None,
    scope: Optional[str] = None,
    themes: Optional[str] = None,
    sort: Optional[str] = None,
):
    days_int = _parse_days(days)
    source_scope = _normalize_source_scope(scope)
    theme_labels = _parse_themes_param(themes)
    sort_val = _normalize_sort(sort)
    active_feed_id = feed_id if source_scope == SOURCE_SCOPE_MY else None
    conn = get_db()
    feeds_rows = conn.execute(
        "SELECT id, url, title, color FROM feeds WHERE COALESCE(subscribed, 1) = 1 ORDER BY title"
    ).fetchall()
    feeds = [dict(f) for f in feeds_rows]

    feed_map = {}
    for f in feeds:
        feed_map[f["id"]] = {
            "title": f["title"],
            "url": f["url"],
            "domain": _feed_host(f["url"]),
            "color": f["color"],
        }

    filters, params = _build_entry_filters(q, active_feed_id, quality_level, days_int, source_scope, theme_labels)
    count_query = "SELECT COUNT(*) FROM entries e JOIN feeds f ON f.id = e.feed_id"
    if filters:
        count_query += " WHERE " + " AND ".join(filters)
    total_entries = conn.execute(count_query, params).fetchone()[0]
    random_seed = _random_seed_from_request(request)
    random_enabled = random_seed is not None

    try:
        max_entries = int(get_setting("max_entries") or "1000")
    except (ValueError, TypeError):
        max_entries = 1000
    if max_entries <= 0:
        max_entries = 1000

    # Only render the first "page" of articles server-side; the rest are
    # fetched lazily via the `/api/entries` endpoint.
    initial_limit = min(max_entries, 40)

    theme_param = ",".join(sorted(theme_labels)) if theme_labels is not None else None
    entries_list = _fetch_ranked_entries(
        conn,
        random_seed,
        q,
        active_feed_id,
        quality_level,
        days_int,
        source_scope,
        theme_labels,
        sort_val,
    )[:initial_limit]

    # Compute trending from recent global entries (not filtered),
    # so the sidebar always has something interesting.
    trending = _load_trending(conn)
    conn.close()

    # If we have any trending entries, treat WordRank as having run successfully
    # so the header/settings status lights stay green while recommendations exist.
    if trending:
        try:
            set_setting("wordrank_last_status", "success")
        except Exception:
            logger.exception("Could not record WordRank status from trending computation")

    return templates.TemplateResponse("index.html", {
        "request": request,
        "feeds": feeds,
        "feed_map": feed_map,
        "entries": entries_list,
        "total_entries": total_entries,
        "total_entries_display": f"{total_entries:,}",
        "trending": trending,
        "q": q or "",
        "active_feed_id": active_feed_id,
        "date_range": days_int if (days_int is not None and days_int in DATE_RANGE_DAYS) else None,
        "quality_level": quality_level,
        "source_scope": source_scope,
        "sort": sort_val,
        "my_feed_url": _build_url_with_query_params("/", {
            "q": q or None,
            "feed_id": str(active_feed_id) if active_feed_id is not None else None,
            "quality_level": str(quality_level) if quality_level is not None else None,
            "days": str(days_int) if days_int is not None else None,
            "scope": SOURCE_SCOPE_MY,
            "themes": theme_param,
            "sort": sort_val if sort_val != SORT_CHRONOLOGICAL else None,
        }),
        "discover_feed_url": _build_url_with_query_params("/", {
            "q": q or None,
            "quality_level": str(quality_level) if quality_level is not None else None,
            "days": str(days_int) if days_int is not None else None,
            "scope": SOURCE_SCOPE_DISCOVER,
            "themes": theme_param,
            "sort": sort_val if sort_val != SORT_CHRONOLOGICAL else None,
        }),
        "clear_url": _build_url_with_query_params("/", {
            "feed_id": str(active_feed_id) if active_feed_id is not None else None,
            "quality_level": str(quality_level) if quality_level is not None else None,
            "scope": source_scope,
            "themes": theme_param,
            "sort": sort_val if sort_val != SORT_CHRONOLOGICAL else None,
        }),
    })


def _compute_trending(entries: list[dict], limit: int = 10) -> list[dict]:
    """
    Build a small "trending" set that:
    - favours recency (entries are already newest-first)
    - encourages diversity of source (per-feed cap)
    - uses the existing score field to prefer more unique content
    """
    if not entries:
        return []

    # Combine recency (position in list) and score into one ranking value.
    # Newest entries appear first in `entries`.
    n = len(entries)
    ranked = []
    for idx, e in enumerate(entries):
        recency_weight = (n - idx) / n  # 1.0 for newest, down to ~0
        score = float(e.get("score") or 0.0)
        combined = 0.7 * recency_weight + 0.3 * score
        ranked.append((combined, e))

    ranked.sort(key=lambda t: t[0], reverse=True)

    # Greedy pick with per-feed cap to keep sources diverse.
    per_feed_cap = 2
    feed_counts: dict[int, int] = {}
    trending: list[dict] = []
    for _, e in ranked:
        feed_id = int(e.get("feed_id") or 0)
        if feed_id:
            if feed_counts.get(feed_id, 0) >= per_feed_cap:
                continue
            feed_counts[feed_id] = feed_counts.get(feed_id, 0) + 1
        trending.append(e)
        if len(trending) >= limit:
            break

    return trending


@app.get("/article/{entry_id}", response_class=HTMLResponse)
def article_page(request: Request, entry_id: int):
    conn = get_db()
    row = conn.execute(
        """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               e.og_title, e.og_description, e.og_image_url, e.full_content,
               COALESCE(e.read, 0) AS read,
               e.assessment_label,
               e.assessment_label_color
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Article not found.")
    entry = dict(row)
    q = request.query_params.get("q")
    feed_id = _parse_int(request.query_params.get("feed_id"))
    quality_level = _parse_int(request.query_params.get("quality_level"))
    days_int = _parse_days(request.query_params.get("days"))
    source_scope = _normalize_source_scope(request.query_params.get("scope"))
    theme_labels = _parse_themes_param(request.query_params.get("themes"))
    sort_val = _normalize_sort(request.query_params.get("sort"))
    active_feed_id = feed_id if source_scope == SOURCE_SCOPE_MY else None
    back_url = _build_url_with_query_params(
        "/",
        {
            "q": request.query_params.get("q"),
            "feed_id": request.query_params.get("feed_id"),
            "quality_level": request.query_params.get("quality_level"),
            "days": request.query_params.get("days"),
            "scope": request.query_params.get("scope"),
            "themes": ",".join(sorted(theme_labels)) if theme_labels is not None else None,
            "sort": sort_val if sort_val != SORT_CHRONOLOGICAL else None,
        },
    )
    prev_url, next_url = _article_neighbor_urls(
        conn,
        entry_id,
        q,
        active_feed_id,
        quality_level,
        days_int,
        source_scope,
        theme_labels,
        sort_val,
    )
    feed_row = conn.execute("SELECT id, url, title, color FROM feeds WHERE id = ?", (entry["feed_id"],)).fetchone()
    conn.execute("UPDATE entries SET read = 1 WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()

    if feed_row:
        feed_map = _build_feed_map([dict(feed_row)])
    else:
        feed_map = {entry["feed_id"]: {"title": entry["feed_title"], "domain": "", "color": None}}
    return templates.TemplateResponse("article.html", {
        "request": request,
        "entry": entry,
        "feed_map": feed_map,
        "back_url": back_url,
        "prev_article_url": prev_url,
        "next_article_url": next_url,
    })


def _build_feed_map(feeds: list[dict]) -> dict:
    out = {}
    for f in feeds:
        out[f["id"]] = {
            "title": f.get("title"),
            "url": f.get("url"),
            "domain": _feed_host(f.get("url")),
            "color": f.get("color"),
        }
    return out


@app.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, url, title, color FROM feeds WHERE COALESCE(subscribed, 1) = 1 ORDER BY LOWER(COALESCE(title, url))"
    ).fetchall()
    trending = _load_trending(conn)
    conn.close()
    feeds = [dict(r) for r in rows]
    feed_map = _build_feed_map(feeds)
    random_enabled = _random_enabled_from_request(request)
    return templates.TemplateResponse(
        "feeds.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "trending": trending,
            "q": "",
            "active_feed_id": None,
            "random_enabled": random_enabled,
        },
    )


@app.get("/add-feed", response_class=HTMLResponse)
def add_feed_page(request: Request):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, url, title, color FROM feeds WHERE COALESCE(subscribed, 1) = 1 ORDER BY title"
    ).fetchall()
    conn.close()
    feeds = [dict(r) for r in rows]
    feed_map = _build_feed_map(feeds)
    random_enabled = _random_enabled_from_request(request)
    return templates.TemplateResponse(
        "add_feed.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "feeds_json": json.dumps(feeds),
            "q": "",
            "active_feed_id": None,
            "random_enabled": random_enabled,
        },
    )


@app.get("/discover", response_class=HTMLResponse)
def discover_page(request: Request):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, url, title, color FROM feeds WHERE COALESCE(subscribed, 1) = 1 ORDER BY title"
    ).fetchall()
    service_rows = conn.execute(
        """
        SELECT
            f.id,
            f.url,
            COALESCE(f.subscribed, 1) AS subscribed,
            (
                SELECT COUNT(*)
                FROM entries e
                WHERE e.feed_id = f.id
            ) AS entry_count
        FROM feeds f
        """
    ).fetchall()
    conn.close()
    feeds = [dict(r) for r in rows]
    service_feeds = [dict(r) for r in service_rows]
    feed_map = _build_feed_map(feeds)
    subscribed = [r["url"] for r in rows]
    random_enabled = _random_enabled_from_request(request)
    return templates.TemplateResponse(
        "discover.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "catalog_json": json.dumps(_get_full_catalog()),
            "subscribed_json": json.dumps(subscribed),
            "service_feeds_json": json.dumps(service_feeds),
            "q": "",
            "active_feed_id": None,
            "random_enabled": random_enabled,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, url, title, color FROM feeds WHERE COALESCE(subscribed, 1) = 1 ORDER BY title"
    ).fetchall()
    conn.close()
    feeds = [dict(r) for r in rows]
    feed_map = _build_feed_map(feeds)
    current = {key: get_setting(key) for key in DEFAULTS}
    if "max_entries" not in current:
        current["max_entries"] = get_setting("max_entries")
    random_enabled = _random_enabled_from_request(request)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "settings": current,
            "q": "",
            "active_feed_id": None,
            "random_enabled": random_enabled,
        },
    )


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    """
    Overview dashboard with cheap-to-compute library statistics.
    """
    conn = get_db()

    # Basic article and feed counts
    total_articles = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    total_feeds = conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]

    # Read/liked breakdown
    unread_articles = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE COALESCE(read, 0) = 0"
    ).fetchone()[0]
    liked_articles = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE COALESCE(liked, 0) = 1"
    ).fetchone()[0]

    # Simple recency stats
    newest_row = conn.execute(
        "SELECT published FROM entries WHERE published IS NOT NULL "
        "ORDER BY published DESC LIMIT 1"
    ).fetchone()
    oldest_row = conn.execute(
        "SELECT published FROM entries WHERE published IS NOT NULL "
        "ORDER BY published ASC LIMIT 1"
    ).fetchone()
    newest_published = newest_row[0] if newest_row else None
    oldest_published = oldest_row[0] if oldest_row else None

    # Top sources by article count
    top_sources_rows = conn.execute(
        """
        SELECT f.id,
               f.title AS feed_title,
               f.url   AS feed_url,
               COUNT(e.id) AS article_count
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        GROUP BY f.id, f.title, f.url
        ORDER BY article_count DESC
        LIMIT 10
        """
    ).fetchall()
    top_sources = [dict(r) for r in top_sources_rows]

    # Top themes (if topic clustering has been run)
    top_themes: list[dict] = []
    try:
        theme_rows = conn.execute(
            "SELECT label, size FROM viz_themes ORDER BY size DESC LIMIT 10"
        ).fetchall()
        top_themes = [dict(r) for r in theme_rows]
    except Exception:
        top_themes = []

    # Daily counts for the last 7 days (cheap aggregate)
    recent_counts_rows = conn.execute(
        """
        SELECT DATE(published) AS day, COUNT(*) AS count
        FROM entries
        WHERE published IS NOT NULL
          AND DATE(published) >= DATE('now', '-6 day')
        GROUP BY DATE(published)
        ORDER BY day ASC
        """
    ).fetchall()
    recent_counts = [dict(r) for r in recent_counts_rows]

    conn.close()
    random_enabled = _random_enabled_from_request(request)

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "total_articles": total_articles,
            "total_feeds": total_feeds,
            "unread_articles": unread_articles,
            "liked_articles": liked_articles,
            "newest_published": newest_published,
            "oldest_published": oldest_published,
            "top_sources": top_sources,
            "top_themes": top_themes,
            "recent_counts": recent_counts,
            "q": "",
            "random_enabled": random_enabled,
        },
    )


# ── Feed API ──────────────────────────────────────────────────────────────────

@app.get("/api/feeds", response_model=list[FeedOut])
def list_feeds():
    """List only subscribed feeds (My Feeds). Catalogue feeds are in DB for training but hidden here."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, url, title, color FROM feeds WHERE COALESCE(subscribed, 1) = 1 ORDER BY title"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/feeds", response_model=FeedOut, status_code=201)
def add_feed(feed: FeedCreate):
    conn = get_db()
    url = str(feed.url)
    title = feed.title or None
    existing = conn.execute("SELECT id, url, title, color FROM feeds WHERE url = ?", (url,)).fetchone()
    if existing:
        conn.execute("UPDATE feeds SET subscribed = 1, title = COALESCE(?, title) WHERE id = ?", (title, existing["id"]))
        conn.commit()
        row = conn.execute("SELECT id, url, title, color FROM feeds WHERE id = ?", (existing["id"],)).fetchone()
        conn.close()
        _add_to_user_catalog(url, title or row["title"] or url)
        return dict(row)
    try:
        row = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1) RETURNING id, url, title, color",
            (url, title),
        ).fetchone()
        conn.commit()
    except Exception as exc:
        conn.close()
        raise HTTPException(status_code=409, detail="Feed URL already exists.") from exc
    conn.close()
    _add_to_user_catalog(url, title or url)
    return dict(row)


@app.patch("/api/feeds/{feed_id}", response_model=FeedOut)
def update_feed(feed_id: int, payload: FeedUpdate):
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    conn = get_db()
    try:
        cols = ", ".join(f"{key} = ?" for key in updates.keys())
        values = list(updates.values()) + [feed_id]
        row = conn.execute(
            f"UPDATE feeds SET {cols} WHERE id = ? RETURNING id, url, title, color, COALESCE(subscribed, 1) AS subscribed",
            values,
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Feed not found.")
    return dict(row)


@app.delete("/api/feeds/{feed_id}", status_code=204)
def delete_feed(feed_id: int):
    """Unsubscribe from a feed; keep feed and entries in DB for training/quality signals."""
    conn = get_db()
    conn.execute("UPDATE feeds SET subscribed = 0 WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()


@app.post("/api/feeds/{feed_id}/subscribe", response_model=FeedOut)
def subscribe_feed(feed_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            "UPDATE feeds SET subscribed = 1 WHERE id = ? RETURNING id, url, title, color, COALESCE(subscribed, 1) AS subscribed",
            (feed_id,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Feed not found.")
    _add_to_user_catalog(row["url"], row["title"] or row["url"])
    return dict(row)


@app.delete("/api/feeds/{feed_id}/service", status_code=204)
def remove_feed_from_service(feed_id: int):
    """Completely remove a feed and all of its entries from the service DB."""
    conn = get_db()
    try:
        feed = conn.execute("SELECT id, url FROM feeds WHERE id = ?", (feed_id,)).fetchone()
        if not feed:
            conn.close()
            raise HTTPException(status_code=404, detail="Feed not found.")
        conn.execute("DELETE FROM entries WHERE feed_id = ?", (feed_id,))
        conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
        try:
            conn.execute("DELETE FROM user_catalog WHERE url = ?", (feed["url"],))
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


# ── Catalogue API ──────────────────────────────────────────────────────────


@app.delete("/api/catalog", status_code=204)
def remove_from_catalog(payload: CatalogRemoveRequest):
    """
    Remove a feed from the user catalogue (so it disappears from Discover),
    and unsubscribe it as well.
    """
    url = str(payload.url)
    conn = get_db()
    try:
        # Best-effort: the table should exist, but don't break if an older DB
        # lacks it (in which case "remove" is a no-op for catalogue).
        try:
            conn.execute("DELETE FROM user_catalog WHERE url = ?", (url,))
        except Exception:
            pass

        # Always unsubscribe: Discover removals should clean up subscriptions.
        conn.execute("UPDATE feeds SET subscribed = 0 WHERE url = ?", (url,))
        conn.commit()
    finally:
        conn.close()


# ── Entries API ───────────────────────────────────────────────────────────────

@app.get("/api/entries", response_model=list[EntryOut])
def list_entries(
    request: Request,
    q: Optional[str] = None,
    feed_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    quality_level: Optional[int] = None,
    days: Optional[str] = None,
    scope: Optional[str] = None,
    themes: Optional[str] = None,
    sort: Optional[str] = None,
):
    """
    List entries with optional sort (chronological, quality_desc, quality_asc).
    The `limit` and `offset` parameters are used by the UI to implement
    lazy-loading on the main articles page.
    """
    days_int = _parse_days(days)
    sort_val = _normalize_sort(sort)
    conn = get_db()
    if limit <= 0:
        limit = 100
    if offset < 0:
        offset = 0
    random_seed = _random_seed_from_request(request)
    source_scope = _normalize_source_scope(scope)
    active_feed_id = feed_id if source_scope == SOURCE_SCOPE_MY else None
    theme_labels = _parse_themes_param(themes)
    rows = _fetch_ranked_entries(
        conn,
        random_seed,
        q,
        active_feed_id,
        quality_level,
        days_int,
        source_scope,
        theme_labels,
        sort_val,
    )
    conn.close()
    return rows[offset : offset + limit]


@app.post("/api/entries/{entry_id}/read", status_code=200)
def mark_read(entry_id: int):
    conn = get_db()
    conn.execute("UPDATE entries SET read = 1 WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/entries/{entry_id}/like", status_code=200)
def toggle_like(entry_id: int, response: Any):
    conn = get_db()
    row = conn.execute("SELECT COALESCE(liked, 0) AS liked FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Entry not found.")
    new_liked = 0 if row["liked"] else 1
    conn.execute("UPDATE entries SET liked = ? WHERE id = ?", (new_liked, entry_id))
    conn.commit()
    conn.close()
    direction = 1 if new_liked else -1
    _set_walk_state_cookie(response, entry_id, direction, WALK_INITIAL_STRENGTH)
    return {
        "liked": bool(new_liked),
        "walk": {"anchor_id": entry_id, "direction": direction, "strength": WALK_INITIAL_STRENGTH},
    }


@app.post("/api/entries/{entry_id}/vote", status_code=200)
def set_like(entry_id: int, payload: EntryVoteUpdate, response: Any):
    conn = get_db()
    row = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Entry not found.")
    new_liked = 1 if payload.liked else 0
    conn.execute("UPDATE entries SET liked = ? WHERE id = ?", (new_liked, entry_id))
    conn.commit()
    conn.close()
    direction = 1 if new_liked else -1
    _set_walk_state_cookie(response, entry_id, direction, WALK_INITIAL_STRENGTH)
    return {
        "liked": bool(new_liked),
        "walk": {"anchor_id": entry_id, "direction": direction, "strength": WALK_INITIAL_STRENGTH},
    }


@app.get("/api/random-article")
def get_random_article(
    request: Request,
    response: Any,
    q: Optional[str] = None,
    feed_id: Optional[int] = None,
    quality_level: Optional[int] = None,
    days: Optional[str] = None,
    scope: Optional[str] = None,
    themes: Optional[str] = None,
    exclude_id: Optional[int] = None,
    exclude_ids: Optional[str] = None,
    walk_anchor_id: Optional[int] = None,
    walk_direction: Optional[int] = None,
    walk_strength: Optional[float] = None,
):
    conn = get_db()
    days_int = _parse_days(days)
    source_scope = _normalize_source_scope(scope)
    theme_labels = _parse_themes_param(themes)
    walk_anchor_id, walk_direction, walk_state_strength = _read_walk_state(
        request,
        walk_anchor_id=walk_anchor_id,
        walk_direction=walk_direction,
    )
    effective_walk_strength = _normalize_walk_strength(walk_strength)
    if effective_walk_strength is None:
        effective_walk_strength = walk_state_strength
    row = _fetch_random_entry(
        conn,
        q,
        feed_id,
        quality_level,
        days_int,
        source_scope,
        theme_labels,
        exclude_id=exclude_id,
        exclude_ids=exclude_ids,
        walk_anchor_id=walk_anchor_id,
        walk_direction=walk_direction,
        walk_strength=effective_walk_strength,
    )
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No matching articles found.")

    if walk_anchor_id is not None and walk_direction is not None:
        next_strength = max(0.0, effective_walk_strength * WALK_DECAY_FACTOR)
        _set_walk_state_cookie(response, walk_anchor_id, walk_direction, next_strength)

    article_url = _build_url_with_query_params(
        f"/article/{row['id']}",
        {
            "q": q,
            "feed_id": str(feed_id) if feed_id is not None else None,
            "quality_level": str(quality_level) if quality_level is not None else None,
            "days": str(days_int) if days_int is not None else None,
            "scope": source_scope if source_scope != SOURCE_SCOPE_MY else None,
            "themes": ",".join(sorted(theme_labels)) if theme_labels is not None else None,
        },
    )
    return {
        "id": row["id"],
        "article_url": article_url,
        "entry": _finalize_entry_row(row),
    }


# ── Settings API ──────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    return {key: get_setting(key) for key in DEFAULTS}


@app.post("/api/settings")
def update_settings(payload: SettingsUpdate):
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        set_setting(key, str(value))
    reconfigure_scheduler()
    return {key: get_setting(key) for key in DEFAULTS}


# ── Refresh API ───────────────────────────────────────────────────────────────

@app.post("/api/refresh", status_code=202)
def trigger_refresh():
    if is_pipeline_running():
        return {"status": "running", "message": "Pipeline already in progress."}
    started = run_pipeline_async()
    if not started:
        return {"status": "running", "message": "Pipeline already in progress."}
    return {"status": "started", "message": "Pipeline started in background."}


@app.get("/api/refresh/status")
def get_refresh_status():
    running = is_pipeline_running()
    last_status = get_setting("pipeline_last_status") or "never"
    minutes_since_last_success: Optional[int] = None
    ts = get_setting("pipeline_last_success_ts")
    if ts:
        try:
            last_dt = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            diff = now - last_dt
            minutes_since_last_success = max(0, int(diff.total_seconds() // 60))
        except Exception:
            minutes_since_last_success = None
    return {
        "running": running,
        "last_status": last_status,
        "minutes_since_last_success": minutes_since_last_success,
    }


# ── Search API ────────────────────────────────────────────────────────────────

@app.get("/api/search")
def live_search(
    q: Optional[str] = None,
    limit: int = 8,
    feed_id: Optional[int] = None,
    quality_level: Optional[int] = None,
    days: Optional[str] = None,
    scope: Optional[str] = None,
):
    if not q or not q.strip():
        return {"suggestions": [], "entries": []}
    q = q.strip()
    conn = get_db()
    days_int = _parse_days(days)
    source_scope = _normalize_source_scope(scope)
    active_feed_id = feed_id if source_scope == SOURCE_SCOPE_MY else None
    filters, params = _build_entry_filters(q, active_feed_id, quality_level, days_int, source_scope, None)
    query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published,
               e.assessment_label,
               e.assessment_label_color
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
    """
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY e.published DESC\n        LIMIT ?\n        "
    entry_rows = conn.execute(query, params + [limit]).fetchall()

    words_in_q = q.split()
    last_word = words_in_q[-1] if words_in_q else ""
    suggestions: list[str] = []
    if last_word and len(last_word) >= 2:
        suggestion_filters, suggestion_params = _build_entry_filters(
            None,
            active_feed_id,
            quality_level,
            days_int,
            source_scope,
            None,
        )
        title_query = """
            SELECT e.title
            FROM entries e
            JOIN feeds f ON f.id = e.feed_id
        """
        title_filters = list(suggestion_filters)
        title_filters.append("e.title LIKE ?")
        title_query += " WHERE " + " AND ".join(title_filters)
        title_query += " LIMIT 200"
        title_rows = conn.execute(title_query, suggestion_params + [f"%{last_word}%"]).fetchall()
        seen: set[str] = set()
        for row in title_rows:
            for word in re.findall(r"[A-Za-z']+", row["title"]):
                wl = word.lower()
                if wl.startswith(last_word.lower()) and wl != last_word.lower() and len(wl) > len(last_word) and wl not in seen:
                    seen.add(wl)
                    suggestions.append(word)
                    if len(suggestions) >= 8:
                        break
            if len(suggestions) >= 8:
                break
    conn.close()
    return {"suggestions": suggestions, "entries": [dict(r) for r in entry_rows]}


# ── Discover API ──────────────────────────────────────────────────────────────

@app.post("/api/discover/detect")
def detect_feeds(payload: DetectRequest):
    import socket
    raw_url = payload.url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.netloc:
        raise HTTPException(status_code=422, detail="Invalid URL.")
    try:
        addr = socket.getaddrinfo(parsed.hostname, None)[0][4][0]
        if any(addr.startswith(p) for p in ("127.", "10.", "192.168.", "169.254.", "::1")):
            raise HTTPException(status_code=422, detail="Private network addresses are not allowed.")
    except HTTPException:
        raise
    except Exception:
        pass

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.feeds = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() != "link":
                return
            d = dict(attrs)
            t = d.get("type", "").lower()
            if t in ("application/rss+xml", "application/atom+xml", "application/rdf+xml"):
                href = d.get("href", "")
                if href:
                    self.feeds.append({"name": d.get("title", ""), "url": href})

    headers = {"User-Agent": "myRSSfeed/1.0 (RSS discovery)"}
    req = urllib.request.Request(raw_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read(512 * 1024).decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=422, detail=f"Could not reach URL: {exc.reason}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Request failed: {exc}")

    if any(t in content_type for t in ("rss", "atom", "xml")):
        title = ""
        m = re.search(r"<title[^>]*>([^<]{1,120})</title>", body, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
        return {"feeds": [{"name": title or "Feed", "url": raw_url}]}

    parser = LinkParser()
    parser.feed(body)
    feeds = []
    seen = set()
    for f in parser.feeds:
        url = urllib.parse.urljoin(raw_url, f["url"])
        if url not in seen:
            seen.add(url)
            feeds.append({"name": f["name"], "url": url})

    if not feeds:
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in ["/rss", "/feed", "/rss.xml", "/atom.xml", "/feed.xml", "/blog/feed", "/blog/rss"]:
            probe_url = base + path
            try:
                probe_req = urllib.request.Request(probe_url, headers=headers, method="HEAD")
                with urllib.request.urlopen(probe_req, timeout=4) as r:
                    ct = r.headers.get("Content-Type", "")
                    if any(t in ct for t in ("rss", "atom", "xml")) and probe_url not in seen:
                        seen.add(probe_url)
                        feeds.append({"name": "", "url": probe_url})
            except Exception:
                continue

    return {"feeds": feeds[:8]}


# ── Newsletter / WordRank API ────────────────────────────────────────────

@app.post("/api/newsletters/sync", status_code=202)
def trigger_newsletter_sync():
    started = run_newsletter_ingest_async(require_enabled=True)
    if not started:
        return {"status": "running", "message": "Newsletter sync already in progress."}
    return {"status": "started", "message": "Newsletter sync started in background."}


@app.get("/api/newsletters/status")
def get_newsletter_status():
    running = is_newsletter_running()
    newsletter_enabled = (get_setting("newsletter_enabled") or "false").lower() == "true"

    last_status = get_setting("newsletter_last_status") or "never"
    if not newsletter_enabled and not running:
        last_status = "disabled"

    return {
        "running": running,
        "last_status": last_status,
        "minutes_since_last_success": _minutes_since_iso_timestamp(get_setting("newsletter_last_success_ts")),
        "last_error": get_setting("newsletter_last_error") or "",
    }


@app.post("/api/wordrank", status_code=200)
def run_wordrank_now():
    # Keep this request synchronous: the frontend expects the POST call to
    # complete WordRank and return `{"status":"success"}` on completion.
    from scripts.wordrank import run_wordrank

    run_wordrank()
    final_status = get_setting("wordrank_last_status") or "never"
    if final_status == "success":
        return {"status": "success", "message": "WordRank completed."}
    return {"status": "error", "message": "WordRank failed."}


@app.get("/api/wordrank/status")
def get_wordrank_status():
    last_status = get_setting("wordrank_last_status") or "never"
    running = last_status == "running"
    return {
        "running": running,
        "last_status": last_status,
        "minutes_since_last_success": _minutes_since_iso_timestamp(get_setting("wordrank_last_success_ts")),
    }


# ── Logs API ──────────────────────────────────────────────────────────────────

@app.get("/api/logs")
def get_logs(lines: int = 100):
    if not os.path.exists(LOG_FILE):
        return {"lines": []}
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return {"lines": [l.rstrip("\n") for l in all_lines[-lines:]]}
    except Exception as exc:
        logger.warning("Could not read log file: %s", exc)
        return {"lines": []}


if __name__ == "__main__":
    host = os.environ.get("MYRSSFEED_SERVER_HOST", "0.0.0.0")
    port_raw = os.environ.get("MYRSSFEED_SERVER_PORT", "8080")
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 8080
    uvicorn.run("main:app", host=host, port=port, reload=False)
