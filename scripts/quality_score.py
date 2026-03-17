# Quality and spam-style scoring from corpus and user signals.
# Used to surface better content and downrank low-quality / spam-like entries.

import os
import re
import logging
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.helpers import get_db  # noqa: E402

logger = logging.getLogger(__name__)

# Heuristic weights
MIN_TITLE_LEN = 5
MIN_SUMMARY_LEN = 20
LABEL_STYLES = [
    ("high", "#2f9e44"),
    ("normal", "#d97706"),
    ("low", "#c92a2a"),
]
SPAM_PATTERNS = [
    r"\b(click here|read more|subscribe now|free (gift|trial|download))\b",
    r"\b(won't believe|you need to see|doctors hate|one weird trick)\b",
    r"\$\d+(\s*(off|%)\s*)?(free|sale)?",
    r"\b(act now|limited time|last chance|hurry)\b",
]
SPAM_RE = re.compile("|".join(f"(?:{p})" for p in SPAM_PATTERNS), re.I)


def _ensure_quality_column(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}
    if "quality_score" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN quality_score REAL DEFAULT 0.0")
        conn.commit()


def _ensure_label_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}
    if "assessment_label" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN assessment_label TEXT")
    if "assessment_label_color" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN assessment_label_color TEXT")
    conn.commit()


def _heuristic_score(title: Optional[str], summary: Optional[str]) -> float:
    """0–1 score from title/summary length and spam-like patterns."""
    title = (title or "").strip()
    summary = (summary or "").strip()
    score = 0.5
    if len(title) >= 80:
        score += 0.15
    elif len(title) >= 30:
        score += 0.1
    elif len(title) >= MIN_TITLE_LEN:
        score += 0.05
    else:
        score -= 0.2
    if len(summary) >= 200:
        score += 0.2
    elif len(summary) >= 80:
        score += 0.1
    elif len(summary) >= MIN_SUMMARY_LEN:
        score += 0.05
    else:
        score -= 0.1
    if SPAM_RE.search(title + " " + summary):
        score -= 0.3
    return max(0.0, min(1.0, score))


def _label_from_quality(quality: float) -> tuple[str, str]:
    """Map a score to a stable label and color."""
    if quality >= 0.72:
        return LABEL_STYLES[0]
    if quality >= 0.45:
        return LABEL_STYLES[1]
    return LABEL_STYLES[2]


def run_quality_score() -> None:
    """
    Compute quality_score for all entries using heuristics and feed-level liked ratio.
    Feeds with higher liked rates get a small boost so the model favours sources the user likes.
    """
    conn = get_db()
    _ensure_quality_column(conn)
    _ensure_label_columns(conn)

    rows = conn.execute(
        "SELECT id, title, summary, feed_id, liked FROM entries"
    ).fetchall()
    if not rows:
        conn.close()
        return

    # Feed-level liked ratio (training signal)
    feed_stats = {}
    for r in conn.execute(
        """
        SELECT feed_id,
               COUNT(*) AS total,
               SUM(COALESCE(liked, 0)) AS liked
        FROM entries GROUP BY feed_id
        """
    ).fetchall():
        total = max(1, r["total"])
        feed_stats[r["feed_id"]] = (r["liked"] or 0) / total

    updates = []
    for r in rows:
        base = _heuristic_score(r["title"], r["summary"])
        feed_boost = feed_stats.get(r["feed_id"], 0) * 0.1  # up to +0.1 from feed liked ratio
        quality = max(0.0, min(1.0, base + feed_boost))
        label, color = _label_from_quality(quality)
        updates.append((quality, label, color, r["id"]))

    conn.executemany(
        "UPDATE entries SET quality_score = ?, assessment_label = ?, assessment_label_color = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    conn.close()
    logger.info("Quality scores updated for %d entries.", len(updates))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_quality_score()
