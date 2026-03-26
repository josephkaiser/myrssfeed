# Quality and spam-style scoring from title/summary heuristics.
# Used to surface better content and downrank low-quality / spam-like entries.

import os
import re
import logging
import sys
import urllib.parse
import math
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.helpers import get_db, get_setting  # noqa: E402

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
TRACKING_RE = re.compile(
    r"(utm_[a-z]+|gclid|fbclid|msclkid|clickid=|affiliate=|aff(_|iliate)?=|ref=|partner=)",
    re.I,
)

DEFAULT_MAJOR_PUBLICATION_DOMAINS: set[str] = {"wsj.com", "nytimes.com"}
MAJOR_PUBLICATION_DOMAINS_SETTING_KEY = "major_publication_domains"
MAJOR_PUBLICATION_BOOST_SETTING_KEY = "major_publication_quality_boost"
DEFAULT_MAJOR_PUBLICATION_BOOST = 0.08

MAJOR_PUBLICATION_SIMILARITY_WEIGHT_SETTING_KEY = "major_publication_similarity_weight"
DEFAULT_MAJOR_PUBLICATION_SIMILARITY_WEIGHT = 0.08
DEFAULT_MAJOR_PUBLICATION_MAJOR_MULTIPLIER = 0.6

SIMILARITY_SIGNATURE_TOP_TOKENS = 500

# Small stopword set so similarity weights don't get dominated by boilerplate.
_SIMILARITY_STOPWORDS: set[str] = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "as",
    "it",
    "this",
    "that",
    "these",
    "those",
    "you",
    "we",
    "they",
    "i",
    "he",
    "she",
    "their",
    "our",
    "your",
}


def _feed_host(feed_url: Optional[str]) -> str:
    parsed = urllib.parse.urlparse(feed_url or "")
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return ""
    host = (parsed.hostname or parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _major_domains() -> set[str]:
    raw = get_setting(MAJOR_PUBLICATION_DOMAINS_SETTING_KEY)
    extra: set[str] = set()
    if raw:
        for part in str(raw).split(","):
            d = part.strip().lower()
            if not d:
                continue
            if d.startswith("www."):
                d = d[4:]
            extra.add(d)
    return DEFAULT_MAJOR_PUBLICATION_DOMAINS | extra


def _parse_float_setting(key: str, default: float) -> float:
    raw = get_setting(key)
    if not raw:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    if val != val:  # NaN
        return default
    return max(0.0, min(0.25, val))


def _is_major_publication(host: str, major_domains: set[str]) -> bool:
    if not host:
        return False
    if host in major_domains:
        return True
    return any(host.endswith("." + d) for d in major_domains)


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


def _heuristic_score(
    title: Optional[str],
    summary: Optional[str],
    link: Optional[str] = None,
    *,
    is_major_publication: bool = False,
    major_publication_boost: float = DEFAULT_MAJOR_PUBLICATION_BOOST,
) -> float:
    """
    0–1 quality proxy from information density + readability + spam checks.

    This is intentionally deterministic and cheap: no model calls, no network.
    """
    title = (title or "").strip()
    summary = (summary or "").strip()
    link = (link or "").strip()
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
    spam_text = bool(SPAM_RE.search(text))
    if spam_text:
        score -= 0.28

    # 5) Spammy tracking / affiliate-style URLs.
    # Cheap safety check: many low-quality feeds wrap promos in tracked links.
    # Kept intentionally mild to avoid penalizing benign UTM usage too hard.
    if link and TRACKING_RE.search(link[:512]):
        score -= 0.08
        if spam_text:
            score -= 0.08

    # Small boost for normal news-like punctuation balance.
    punct_ratio = sum(1 for ch in text if ch in ",.;:!?") / max(1, len(text))
    if 0.01 <= punct_ratio <= 0.07:
        score += 0.03

    # 6) Mild prior: known major publications.
    # This helps ranking when heuristics over/under-estimate specific feeds.
    # Keep it small and only apply when the content isn't already very low.
    if is_major_publication and score >= 0.2:
        score += major_publication_boost

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
    (length and spam-like pattern detection), plus a light publisher prior.
    """
    conn = get_db()
    _ensure_quality_column(conn)
    _ensure_label_columns(conn)

    major_domains = _major_domains()
    major_boost = _parse_float_setting(MAJOR_PUBLICATION_BOOST_SETTING_KEY, DEFAULT_MAJOR_PUBLICATION_BOOST)
    similarity_weight = _parse_float_setting(
        MAJOR_PUBLICATION_SIMILARITY_WEIGHT_SETTING_KEY,
        DEFAULT_MAJOR_PUBLICATION_SIMILARITY_WEIGHT,
    )

    rows = conn.execute(
        """
        SELECT e.id, e.title, e.summary, e.link, f.url AS feed_url
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        """
    ).fetchall()
    if not rows:
        conn.close()
        return

    # Build a "NYT/WSJ signature" word model:
    # token weights are proportional to how much more common a token is in
    # major-publisher entries than in the rest of your library.
    #
    # This is intentionally cheap: simple token counts + log-ratio, no ML.
    token_weights: dict[str, float] = {}
    if similarity_weight > 0:
        major_total_tokens = 0
        total_tokens = 0
        major_token_counts: dict[str, int] = {}
        total_token_counts: dict[str, int] = {}

        for r in rows:
            host = _feed_host(r["feed_url"])
            is_major = _is_major_publication(host, major_domains)

            title = r["title"] or ""
            summary = r["summary"] or ""
            tokens = [t.lower() for t in WORD_RE.findall(f"{title} {summary}") if len(t) >= 3]

            # We also need per-token frequencies; rebuild a small per-entry
            # counter (cheap for our token volumes).
            per_entry: dict[str, int] = {}
            for tok in tokens:
                if tok in _SIMILARITY_STOPWORDS:
                    continue
                per_entry[tok] = per_entry.get(tok, 0) + 1

            for tok, cnt in per_entry.items():
                total_token_counts[tok] = total_token_counts.get(tok, 0) + cnt
                total_tokens += cnt
                if is_major:
                    major_token_counts[tok] = major_token_counts.get(tok, 0) + cnt
                    major_total_tokens += cnt

        if major_total_tokens > 0 and total_tokens > 0:
            eps = 1e-12
            weighted: list[tuple[str, float]] = []
            for tok, major_cnt in major_token_counts.items():
                overall_cnt = total_token_counts.get(tok, 0)
                major_ratio = major_cnt / max(1, major_total_tokens)
                overall_ratio = overall_cnt / max(1, total_tokens)
                # Log odds-ish ratio; we clamp at 0 so only "major-leaning"
                # words can contribute.
                w = math.log((major_ratio + eps) / (overall_ratio + eps))
                if w > 0:
                    weighted.append((tok, w))

            weighted.sort(key=lambda x: x[1], reverse=True)
            for tok, w in weighted[:SIMILARITY_SIGNATURE_TOP_TOKENS]:
                token_weights[tok] = w

    # Now compute quality scores, including the publisher prior and similarity.
    updates = []
    for r in rows:
        entry_id = int(r["id"])
        host = _feed_host(r["feed_url"])
        is_major = _is_major_publication(host, major_domains)

        base_quality = _heuristic_score(
            r["title"],
            r["summary"],
            r["link"],
            is_major_publication=is_major,
            major_publication_boost=major_boost,
        )

        # Similarity boost against the major-publisher word signature.
        similarity_boost = 0.0
        if similarity_weight > 0 and token_weights:
            # Use set-of-tokens for stability: don't over-boost long summaries.
            title = r["title"] or ""
            summary = r["summary"] or ""
            tokens = [t.lower() for t in WORD_RE.findall(f"{title} {summary}") if len(t) >= 3]
            token_set = {t for t in tokens if t not in _SIMILARITY_STOPWORDS}
            raw = 0.0
            for tok in token_set:
                raw += token_weights.get(tok, 0.0)
            # Map raw >=0 to ~[0,1)
            similarity_score = 1.0 - math.exp(-raw)
            multiplier = DEFAULT_MAJOR_PUBLICATION_MAJOR_MULTIPLIER if is_major else 1.0
            similarity_boost = similarity_weight * similarity_score * multiplier

        quality = max(0.0, min(1.0, base_quality + similarity_boost))
        label, color = _label_from_quality(quality)
        updates.append((quality, label, color, entry_id))

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
