"""
Heuristic theme labeling for feed entries.

This is intentionally lightweight (no model calls) so the UI can filter by
theme immediately, even on constrained hardware.

If you later want model-based `which_theme`, this file can be replaced with a
prompted classifier that writes the same `entries.theme_label*` columns.
"""

import re
import logging
from typing import Optional

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.helpers import get_db  # noqa: E402

logger = logging.getLogger(__name__)

THEME_LABELS: tuple[str, ...] = (
    "Politics",
    "Technology",
    "Business",
    "Stocks",
    "Spam",
    "Science",
    "World News",
)

THEME_COLORS = {
    "Politics": "#2f9e44",
    "Technology": "#1c7ed6",
    "Business": "#d97706",
    "Stocks": "#228be6",
    "Spam": "#c92a2a",
    "Science": "#4dabf7",
    "World News": "#40c057",
}

# Reuse-ish spam patterns from scripts/quality_score.py (kept duplicated to stay standalone).
SPAM_PATTERNS = [
    r"\b(click here|read more|subscribe now|free (gift|trial|download))\b",
    r"\b(won't believe|you need to see|one weird trick)\b",
    r"\$\d+(\s*(off|%)\s*)?(free|sale)?",
    r"\b(act now|limited time|last chance|hurry)\b",
]
SPAM_RE = re.compile("|".join(f"(?:{p})" for p in SPAM_PATTERNS), re.I)


def _ensure_theme_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}
    if "theme_label" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN theme_label TEXT")
    if "theme_label_color" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN theme_label_color TEXT")
    if "theme_confidence" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN theme_confidence REAL DEFAULT 0.0")
    conn.commit()


def _text_blob(title: Optional[str], summary: Optional[str], link: Optional[str], feed_title: Optional[str]) -> str:
    return " ".join([
        title or "",
        summary or "",
        link or "",
        feed_title or "",
    ]).lower()


def _match_any(blob: str, patterns: list[str]) -> bool:
    return any(re.search(p, blob, re.I) for p in patterns)


def classify_theme(title: Optional[str], summary: Optional[str], link: Optional[str], feed_title: Optional[str]) -> tuple[str, float]:
    blob = _text_blob(title, summary, link, feed_title)

    # 1) Spam
    if SPAM_RE.search(blob):
        return "Spam", 0.95

    # 2) Stocks / markets
    stock_patterns = [
        r"\bstocks?\b",
        r"\bmarket(s)?\b",
        r"\b(earnings?|ipo|dividend|trading|nasdaq|nyse|dow|s&p|sp500)\b",
        r"\$\s*\d+",
        r"\b(sec|fomc)\b",
    ]
    if _match_any(blob, stock_patterns):
        return "Stocks", 0.8

    # 3) Politics
    politics_patterns = [
        r"\belection\b",
        r"\b(government|senate|congress|parliament|minister|president|prime minister)\b",
        r"\bvote\b",
        r"\bpolicy\b",
        r"\b(bill|law|legislation)\b",
        r"\b(democrat|republican)\b",
        r"\b(impeachment)\b",
    ]
    if _match_any(blob, politics_patterns):
        return "Politics", 0.78

    # 4) Technology
    tech_patterns = [
        r"\b(ai|artificial intelligence|llm|machine learning)\b",
        r"\b(software|programming|developer|github|api|cloud|kubernetes)\b",
        r"\b(cybersecurity|security breach|ransomware|malware)\b",
        r"\b(chip|semiconductor|processor|gpu)\b",
        r"\b(robotics?|quantum)\b",
    ]
    if _match_any(blob, tech_patterns):
        return "Technology", 0.78

    # 5) Science
    science_patterns = [
        r"\b(study|research|scientists?|experiment|journal)\b",
        r"\b(nasa|space)\b",
        r"\b(physics|chemistry|biology|genome|protein|cell|quantum)\b",
        r"\b(astronomy|climate)\b",
    ]
    if _match_any(blob, science_patterns):
        return "Science", 0.72

    # 6) Business
    business_patterns = [
        r"\bcompany\b",
        r"\bstartup(s)?\b",
        r"\b(revenue|profit|earnings)\b",
        r"\b(merger|acquisition)\b",
        r"\b(bank|lender|economy|inflation|gdp|growth)\b",
        r"\b(cost|pricing|supply chain)\b",
    ]
    if _match_any(blob, business_patterns):
        return "Business", 0.65

    # 7) World news fallback
    return "World News", 0.45


def run_theme_labeling() -> None:
    conn = get_db()
    _ensure_theme_columns(conn)

    rows = conn.execute(
        """
        SELECT e.id, e.title, e.summary, e.link, f.title AS feed_title, e.theme_label
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        WHERE e.theme_label IS NULL OR TRIM(COALESCE(e.theme_label, '')) = ''
        """,
    ).fetchall()

    if not rows:
        conn.close()
        return

    updates = []
    for r in rows:
        theme, confidence = classify_theme(r["title"], r["summary"], r["link"], r["feed_title"])
        updates.append(
            (
                theme,
                THEME_COLORS.get(theme),
                float(confidence),
                r["id"],
            )
        )

    conn.executemany(
        "UPDATE entries SET theme_label = ?, theme_label_color = ?, theme_confidence = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    conn.close()
    logger.info("Theme labeling updated for %d entries.", len(updates))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_theme_labeling()

