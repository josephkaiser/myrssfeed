# Quality and spam-style scoring from title/summary heuristics.
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
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'/-]*")
TITLE_CASE_WORD_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
NOISE_RE = re.compile(r"^\s*(read more|continue reading|advertisement|sponsored)\b", re.I)


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
    """
    0–1 quality proxy from information density + readability + spam checks.

    This is intentionally deterministic and cheap: no model calls, no network.
    """
    title = (title or "").strip()
    summary = (summary or "").strip()
    text = (title + " " + summary).strip()
    score = 0.45

    # Hard failure for mostly empty entries.
    if len(title) < MIN_TITLE_LEN and len(summary) < MIN_SUMMARY_LEN:
        return 0.0

    title_words = WORD_RE.findall(title)
    summary_words = WORD_RE.findall(summary)
    all_words = title_words + summary_words

    # 1) Information completeness (title + summary presence/shape).
    if len(title_words) >= 5:
        score += 0.08
    elif len(title_words) >= 3:
        score += 0.03
    else:
        score -= 0.12

    if len(summary_words) >= 45:
        score += 0.16
    elif len(summary_words) >= 20:
        score += 0.1
    elif len(summary_words) >= 8:
        score += 0.03
    else:
        score -= 0.12

    # 2) Readability / structure signal.
    sentence_count = len(re.findall(r"[.!?]+", summary))
    if sentence_count >= 2:
        score += 0.06
    elif sentence_count == 0 and summary:
        score -= 0.06

    title_case_hits = len(TITLE_CASE_WORD_RE.findall(title))
    if title_case_hits >= 1:
        score += 0.03

    # 3) Redundancy / low-signal penalties.
    if all_words:
        unique_ratio = len({w.lower() for w in all_words}) / max(1, len(all_words))
        if unique_ratio >= 0.65:
            score += 0.06
        elif unique_ratio < 0.4:
            score -= 0.1

    if summary and summary.strip().endswith("..."):
        score -= 0.04
    if NOISE_RE.search(summary):
        score -= 0.12

    upper_chars = sum(1 for ch in text if ch.isupper())
    alpha_chars = sum(1 for ch in text if ch.isalpha())
    if alpha_chars > 0:
        upper_ratio = upper_chars / alpha_chars
        if upper_ratio > 0.38:
            score -= 0.12

    # 4) Spam-like patterns are strong negatives.
    if SPAM_RE.search(text):
        score -= 0.28

    # Small boost for normal news-like punctuation balance.
    punct_ratio = sum(1 for ch in text if ch in ",.;:!?") / max(1, len(text))
    if 0.01 <= punct_ratio <= 0.07:
        score += 0.03

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
    Compute quality_score for all entries using title/summary heuristics
    (length and spam-like pattern detection).
    """
    conn = get_db()
    _ensure_quality_column(conn)
    _ensure_label_columns(conn)

    rows = conn.execute(
        "SELECT id, title, summary FROM entries"
    ).fetchall()
    if not rows:
        conn.close()
        return

    updates = []
    for r in rows:
        quality = _heuristic_score(r["title"], r["summary"])
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
