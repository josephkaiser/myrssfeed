# Requires: scikit-learn>=1.5.0, numpy>=1.26.0

import os
import sys
import re
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.helpers import get_db

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def _ensure_columns():
    conn = get_db()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}
    if "liked" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN liked INTEGER DEFAULT 0")
        logger.info("Added column entries.liked")
    if "score" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN score REAL DEFAULT 0.0")
        logger.info("Added column entries.score")
    conn.commit()
    conn.close()


def run_wordrank() -> None:
    """Recompute WordRank scores for all entries based on liked articles.

    If the optional dependencies (scikit-learn, numpy) are not installed, this
    function logs a warning and returns without raising so the rest of the
    pipeline can still be considered successful.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:
        logger.warning(
            "WordRank: optional dependencies missing, skipping recompute "
            "(install scikit-learn and numpy to enable). Error: %s",
            exc,
        )
        return

    _ensure_columns()

    logger.info("WordRank: loading entries")
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, summary, liked FROM entries"
    ).fetchall()
    conn.close()

    if not rows:
        logger.info("WordRank: no entries found, skipping")
        return

    ids = [r["id"] for r in rows]
    texts = [
        (r["title"] or "") + " " + _strip_html(r["summary"] or "")
        for r in rows
    ]
    liked_mask = [r["liked"] == 1 for r in rows]

    logger.info("WordRank: %d entries, %d liked", len(ids), sum(liked_mask))

    vectorizer = TfidfVectorizer(max_features=5000, stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(texts)

    if any(liked_mask):
        liked_indices = [i for i, v in enumerate(liked_mask) if v]
        centroid = np.asarray(tfidf_matrix[liked_indices].mean(axis=0))
        scores = cosine_similarity(tfidf_matrix, centroid).flatten().tolist()
    else:
        scores = [0.0] * len(ids)

    conn = get_db()
    conn.executemany(
        "UPDATE entries SET score = ? WHERE id = ?",
        [(score, entry_id) for score, entry_id in zip(scores, ids)],
    )
    conn.commit()
    conn.close()

    logger.info("WordRank: scores written for %d entries", len(ids))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_wordrank()
