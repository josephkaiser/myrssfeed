import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import Request

from .constants import (
    DATE_RANGE_DAYS,
    RANDOM_SEED_COOKIE,
    SORT_CHRONOLOGICAL,
    SORT_OPTIONS,
    SOURCE_SCOPE_DISCOVER,
    SOURCE_SCOPE_MY,
    THEME_LABELS,
    WALK_INITIAL_STRENGTH,
    WALK_STATE_COOKIE,
)


def random_seed_from_request(request: Request) -> Optional[int]:
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


def random_enabled_from_request(request: Request) -> bool:
    return random_seed_from_request(request) is not None


def normalize_walk_direction(value: Optional[Union[int, str]]) -> Optional[int]:
    try:
        direction = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if direction > 0:
        return 1
    if direction < 0:
        return -1
    return None


def normalize_walk_strength(value: Optional[Union[int, float, str]]) -> Optional[float]:
    try:
        strength = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if strength != strength:
        return None
    return max(0.0, min(1.0, strength))


def parse_int(value: Optional[Union[int, str]]) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_int_list(value: Optional[str]) -> set[int]:
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


def minutes_since_iso_timestamp(ts: Optional[str]) -> Optional[int]:
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


def parse_days(days_param: Optional[str]) -> Optional[int]:
    if days_param is None or days_param.strip() == "":
        return None
    try:
        days = int(days_param)
        return days if days in DATE_RANGE_DAYS else None
    except ValueError:
        return None


def parse_themes_param(themes_param: Optional[str]) -> Optional[set[str]]:
    if themes_param is None:
        return None
    raw = str(themes_param).strip()
    if raw == "":
        return set()
    allowed = {label.lower(): label for label in THEME_LABELS}
    out: set[str] = set()
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        normalized = allowed.get(piece.lower())
        if normalized:
            out.add(normalized)
    return out


def normalize_source_scope(scope: Optional[str]) -> str:
    raw = (scope or "").strip().lower()
    if raw == SOURCE_SCOPE_DISCOVER:
        return SOURCE_SCOPE_DISCOVER
    return SOURCE_SCOPE_MY


def normalize_sort(sort: Optional[str]) -> str:
    raw = (sort or "").strip().lower()
    if raw in SORT_OPTIONS:
        return raw
    return SORT_CHRONOLOGICAL


def build_url_with_query_params(path: str, params: dict[str, Optional[str]]) -> str:
    cleaned = [(key, value) for key, value in params.items() if value not in (None, "")]
    if not cleaned:
        return path
    return f"{path}?{urllib.parse.urlencode(cleaned)}"
