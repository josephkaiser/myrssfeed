# Requires: ollama running locally (see https://ollama.ai)

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gc
import json
import logging
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone

from utils.helpers import get_db, get_setting

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "ollama_url": "http://localhost:11434",
    "ollama_model": "phi3:mini",
    "digest_max_articles": "50",
}


def _setting(key: str) -> str:
    val = get_setting(key)
    if val == "":
        return _DEFAULTS[key]
    return val


def _ensure_table(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_digests (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            content    TEXT NOT NULL,
            model      TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()


def _has_score_column(conn) -> bool:
    rows = conn.execute("PRAGMA table_info(entries)").fetchall()
    return any(row["name"] == "score" for row in rows)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?]) +", text)
    return [s.strip() for s in parts if s.strip()]


def _score_sentence(sentence: str, title_words: set) -> float:
    """Word overlap with the article title, normalized by sentence length."""
    words = re.findall(r"\w+", sentence.lower())
    if not words:
        return 0.0
    overlap = sum(1 for w in words if w in title_words)
    return overlap / len(words)


def _extract_sentences(title: str, summary: str, n: int = 2) -> str:
    """Return up to n top sentences from summary by title-word overlap."""
    clean = _strip_html(summary)
    sentences = _split_sentences(clean)
    if not sentences:
        return ""

    title_words = set(re.findall(r"\w+", title.lower()))

    scored = sorted(
        enumerate(sentences),
        key=lambda pair: _score_sentence(pair[1], title_words),
        reverse=True,
    )
    top_indices = sorted(idx for idx, _ in scored[:n])
    return " ".join(sentences[i] for i in top_indices)


def _build_extracts(entries, feed_titles: dict) -> list:
    extracts = []
    for row in entries:
        title = row["title"] or "(no title)"
        summary = row["summary"] or ""
        feed_id = row["feed_id"]
        feed_title = feed_titles.get(feed_id) or f"Feed {feed_id}"

        extract = _extract_sentences(title, summary, n=2)
        if not extract:
            extract = _strip_html(summary)[:200].strip()

        line = f"[Feed: {feed_title}] {title}: {extract}"
        extracts.append(line)
    return extracts


def _build_prompt(extracts: list) -> str:
    articles_block = "\n".join(extracts)
    if len(articles_block) > 4000:
        articles_block = articles_block[:4000]

    return (
        "You are summarizing today's RSS feed for a personal reader. "
        "Below are the most relevant articles from today.\n"
        "Write a concise digest with 3-5 thematic sections. "
        "Each section should have a short bold heading and 2-4 bullet points.\n"
        "Focus on the most important news and insights. Be direct and informative.\n\n"
        f"ARTICLES:\n{articles_block}\n\nDIGEST:\n"
    )


def _call_ollama(ollama_url: str, model: str, prompt: str):
    """Stream tokens from ollama to avoid buffering the full response in RAM."""
    url = f"{ollama_url.rstrip('/')}/api/generate"
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": 0,          # unload model from RAM immediately when done
        "options": {
            "num_predict": 600,   # cap output tokens; digest doesn't need more
            "num_ctx": 4096,      # cap KV cache; default 128k uses several GB on Pi
        },
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        chunks: list[str] = []
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw_line in resp:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    data = json.loads(raw_line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                token = data.get("response", "")
                if token:
                    chunks.append(token)
                if data.get("done"):
                    break
        return "".join(chunks) if chunks else None
    except urllib.error.URLError as exc:
        logger.warning("Ollama request failed (URL error): %s", exc)
        return None
    except TimeoutError as exc:
        logger.warning("Ollama request timed out: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Ollama request failed: %s", exc)
        return None


def run_digest() -> None:
    """Generate today's AI digest using ollama."""
    logger.info("Starting digest generation.")

    ollama_url = _setting("ollama_url")
    model = _setting("ollama_model")
    try:
        max_articles = int(_setting("digest_max_articles"))
    except (ValueError, TypeError):
        max_articles = 50

    conn = get_db()
    _ensure_table(conn)

    use_score = _has_score_column(conn)
    order_clause = "e.score DESC, e.published DESC" if use_score else "e.published DESC"
    score_col = "e.score" if use_score else "0.0 AS score"

    rows = conn.execute(
        f"""
        SELECT e.id, e.feed_id, e.title, e.summary, {score_col}
        FROM entries e
        ORDER BY {order_clause}
        LIMIT ?
        """,
        (max_articles,),
    ).fetchall()

    if not rows:
        logger.info("No entries found — skipping digest.")
        conn.close()
        return

    logger.info("Digest: processing %d articles.", len(rows))

    feed_rows = conn.execute("SELECT id, title FROM feeds").fetchall()
    feed_titles = {r["id"]: (r["title"] or "") for r in feed_rows}

    extracts = _build_extracts(rows, feed_titles)
    logger.info("Extractive pre-filter done (%d extracts).", len(extracts))

    prompt = _build_prompt(extracts)

    # Free memory from prior pipeline stages (wordrank/visualization sklearn objects)
    # before asking ollama to load the model into RAM.
    gc.collect()

    logger.info("Calling ollama model=%s at %s", model, ollama_url)
    digest_text = _call_ollama(ollama_url, model, prompt)

    if digest_text is None:
        logger.warning("Ollama call failed or returned no content — digest not stored.")
        conn.close()
        return

    logger.info("LLM digest received (%d chars). Storing.", len(digest_text))

    today = datetime.now(timezone.utc).date().isoformat()
    now_str = datetime.now(timezone.utc).isoformat()

    conn.execute("DELETE FROM daily_digests WHERE date = ?", (today,))
    conn.execute(
        "INSERT INTO daily_digests (date, content, model, created_at) VALUES (?, ?, ?, ?)",
        (today, digest_text, model, now_str),
    )
    conn.commit()
    conn.close()

    logger.info("Digest for %s stored successfully.", today)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_digest()
