import json
import random
from typing import Any, Optional

from fastapi import Request

from .constants import (
    WALK_INITIAL_STRENGTH,
    WALK_MIN_STRENGTH,
    WALK_STATE_COOKIE,
    WALK_STOPWORDS,
    WALK_TOKEN_RE,
)
from .parsing import parse_int, normalize_walk_direction, normalize_walk_strength


def walk_tokens(row: dict) -> set[str]:
    parts = [
        row.get("title") or "",
        row.get("summary") or "",
        row.get("feed_title") or "",
    ]
    tokens: set[str] = set()
    for part in parts:
        for token in WALK_TOKEN_RE.findall(str(part).lower()):
            if len(token) < 3 or token in WALK_STOPWORDS:
                continue
            tokens.add(token)
    return tokens


def walk_similarity(anchor_tokens: set[str], candidate_tokens: set[str]) -> float:
    if not anchor_tokens or not candidate_tokens:
        return 0.0
    overlap = len(anchor_tokens & candidate_tokens)
    if not overlap:
        return 0.0
    return overlap / max(len(anchor_tokens), 1)


def read_walk_state(
    request: Request,
    walk_anchor_id: Optional[int] = None,
    walk_direction: Optional[int] = None,
) -> tuple[Optional[int], Optional[int], float]:
    anchor_id = parse_int(walk_anchor_id)
    direction = normalize_walk_direction(walk_direction)
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
        anchor_id = parse_int(data.get("anchor_id"))
    if direction is None:
        direction = normalize_walk_direction(data.get("direction"))
    cookie_strength = normalize_walk_strength(data.get("strength"))
    if cookie_strength is not None:
        strength = cookie_strength
    elif anchor_id is not None and direction is not None:
        strength = WALK_INITIAL_STRENGTH
    return anchor_id, direction, strength


def set_walk_state_cookie(
    response: Any,
    anchor_id: int,
    direction: int,
    strength: float = WALK_INITIAL_STRENGTH,
) -> None:
    normalized_strength = normalize_walk_strength(strength)
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


def pick_walk_candidate(
    rows: list[dict],
    anchor_row: dict,
    direction: int,
    strength: float,
) -> Optional[dict]:
    if not rows or not anchor_row:
        return None

    anchor_id = int(anchor_row.get("id") or 0)
    anchor_tokens = walk_tokens(anchor_row)
    if not anchor_id or not anchor_tokens:
        return None

    walk_strength = normalize_walk_strength(strength) or 0.0
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

        candidate_tokens = walk_tokens(row)
        similarity = walk_similarity(anchor_tokens, candidate_tokens)
        recency_weight = (total - idx) / total
        score = float(row.get("score") or 0.0)
        same_feed_bonus = (0.06 + 0.04 * walk_strength) if int(row.get("feed_id") or 0) == anchor_feed_id else 0.0
        directional_weight = 0.42 + (0.36 * walk_strength)
        recency_bias = 0.18 + (0.08 * walk_strength)
        score_bias = 0.12 + (0.08 * walk_strength)

        if direction > 0:
            blended = (
                (directional_weight * similarity)
                + (recency_bias * recency_weight)
                + (score_bias * score)
                + same_feed_bonus
            )
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
