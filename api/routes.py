import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import os

from utils.helpers import get_db, get_setting, set_setting, DEFAULTS
from api.schemas import FeedCreate, FeedOut, EntryOut, SettingsUpdate, TopicOut, DigestOut, DigestBullet, LlmDigestOut
from scripts.compile_feed import run_compile_feed

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory ollama pull state ─────────────────────────────────────────────
_pull_state: dict = {"status": "idle", "step": "", "pct": 0, "error": ""}


def _do_pull(ollama_url: str, model: str) -> None:
    """Background thread: stream-pull a model from ollama and track progress."""
    import urllib.request
    import urllib.error
    import json as _json

    global _pull_state
    _pull_state = {"status": "pulling", "step": "Starting…", "pct": 0, "error": ""}

    api_endpoint = ollama_url.rstrip("/") + "/api/pull"
    payload = _json.dumps({"model": model, "stream": True}).encode()
    req = urllib.request.Request(
        api_endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if not line:
                    continue
                try:
                    obj = _json.loads(line)
                except Exception:
                    continue
                status_txt = obj.get("status", "")
                total     = obj.get("total", 0)
                completed = obj.get("completed", 0)
                pct = int(completed / total * 100) if total else _pull_state["pct"]
                _pull_state["step"] = status_txt
                _pull_state["pct"]  = pct
                if status_txt == "success":
                    _pull_state["status"] = "done"
                    _pull_state["pct"]    = 100
                    return
        _pull_state["status"] = "done"
        _pull_state["pct"]    = 100
    except Exception as exc:
        _pull_state["status"] = "error"
        _pull_state["error"]  = str(exc)

_templates_dir = os.path.join(os.path.dirname(__file__), "..", "web", "templates")
templates = Jinja2Templates(directory=_templates_dir)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    current = {key: get_setting(key) for key in DEFAULTS}
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "settings": current},
    )


@router.get("/", response_class=HTMLResponse)
def index(request: Request, q: Optional[str] = None, feed_id: Optional[int] = None):
    conn = get_db()
    feeds = conn.execute("SELECT id, url, title FROM feeds ORDER BY title").fetchall()

    query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
    """
    params: list = []
    filters = []

    if q:
        filters.append("(e.title LIKE ? OR e.summary LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if feed_id:
        filters.append("e.feed_id = ?")
        params.append(feed_id)

    if filters:
        query += " WHERE " + " AND ".join(filters)

    query += " ORDER BY e.published DESC LIMIT 200"
    entries = conn.execute(query, params).fetchall()
    conn.close()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "feeds": [dict(f) for f in feeds],
            "entries": [dict(e) for e in entries],
            "q": q or "",
            "active_feed_id": feed_id,
        },
    )


# ---------------------------------------------------------------------------
# Feed management
# ---------------------------------------------------------------------------

@router.get("/api/feeds", response_model=list[FeedOut])
def list_feeds():
    conn = get_db()
    rows = conn.execute("SELECT id, url, title FROM feeds ORDER BY title").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/feeds", response_model=FeedOut, status_code=201)
def add_feed(feed: FeedCreate):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO feeds (url, title) VALUES (?, ?) RETURNING id, url, title",
            (str(feed.url), feed.title),
        )
        row = cursor.fetchone()
        conn.commit()
    except Exception as exc:
        conn.close()
        raise HTTPException(status_code=409, detail="Feed URL already exists.") from exc
    conn.close()
    return dict(row)


@router.delete("/api/feeds/{feed_id}", status_code=204)
def delete_feed(feed_id: int):
    conn = get_db()
    conn.execute("DELETE FROM entries WHERE feed_id = ?", (feed_id,))
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

@router.get("/api/entries", response_model=list[EntryOut])
def list_entries(
    q: Optional[str] = None,
    feed_id: Optional[int] = None,
    limit: int = 100,
):
    conn = get_db()
    query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
    """
    params: list = []
    filters = []

    if q:
        filters.append("(e.title LIKE ? OR e.summary LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if feed_id:
        filters.append("e.feed_id = ?")
        params.append(feed_id)

    if filters:
        query += " WHERE " + " AND ".join(filters)

    query += " ORDER BY e.published DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/api/settings")
def get_settings():
    return {key: get_setting(key) for key in DEFAULTS}


@router.post("/api/settings")
def update_settings(payload: SettingsUpdate):
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        set_setting(key, str(value))
    return {key: get_setting(key) for key in DEFAULTS}


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

@router.post("/api/refresh", status_code=202)
def trigger_refresh():
    """Manually kick off a feed fetch outside the scheduled window."""
    try:
        run_compile_feed()
    except Exception as exc:
        logger.exception("Manual refresh failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "message": "Feed refresh complete."}


# ---------------------------------------------------------------------------
# Live search (suggestions + previews)
# ---------------------------------------------------------------------------

@router.get("/api/search")
def live_search(q: Optional[str] = None, limit: int = 8):
    """
    Return word-completion suggestions and matching entry previews for a
    partial query string.  Used by the live-search dropdown in the UI.
    """
    import re as _re

    if not q or not q.strip():
        return {"suggestions": [], "entries": []}

    q = q.strip()
    conn = get_db()

    # Matching entries (title or summary)
    entry_rows = conn.execute(
        """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        WHERE e.title LIKE ? OR e.summary LIKE ?
        ORDER BY e.published DESC
        LIMIT ?
        """,
        (f"%{q}%", f"%{q}%", limit),
    ).fetchall()

    # Word completions — look at the last partial word the user typed
    words_in_q = q.split()
    last_word = words_in_q[-1] if words_in_q else ""
    suggestions: list[str] = []

    if last_word and len(last_word) >= 2:
        title_rows = conn.execute(
            "SELECT title FROM entries WHERE title LIKE ? LIMIT 200",
            (f"%{last_word}%",),
        ).fetchall()
        seen: set[str] = set()
        for row in title_rows:
            for word in _re.findall(r"[A-Za-z']+", row["title"]):
                wl = word.lower()
                if (
                    wl.startswith(last_word.lower())
                    and wl != last_word.lower()
                    and len(wl) > len(last_word)
                    and wl not in seen
                ):
                    seen.add(wl)
                    suggestions.append(word)
                    if len(suggestions) >= 8:
                        break
            if len(suggestions) >= 8:
                break

    conn.close()
    return {
        "suggestions": suggestions,
        "entries": [dict(r) for r in entry_rows],
    }


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

@router.get("/api/topics", response_model=list[TopicOut])
def list_topics():
    conn = get_db()
    rows = conn.execute("""
        SELECT tc.id, tc.label, COUNT(et.entry_id) AS article_count
        FROM topic_clusters tc
        LEFT JOIN entry_topics et ON et.cluster_id = tc.id
        GROUP BY tc.id, tc.label
        ORDER BY article_count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/topics/{cluster_id}/entries", response_model=list[EntryOut])
def list_topic_entries(
    cluster_id: int,
    limit: int = 100,
    offset: int = 0,
):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               et.cluster_id, et.score
        FROM entry_topics et
        JOIN entries e ON e.id = et.entry_id
        JOIN feeds f ON f.id = e.feed_id
        WHERE et.cluster_id = ?
        ORDER BY et.score DESC, e.published DESC
        LIMIT ? OFFSET ?
        """,
        (cluster_id, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/digest", response_model=DigestOut)
def get_digest(date: Optional[str] = None):
    """
    Return a bullet-point digest for the given date (YYYY-MM-DD).
    Defaults to today. One bullet per topic cluster that has articles on that day,
    using the highest-scoring entry as the headline. Clusters are ordered by
    article count descending.
    """
    import datetime
    target = date or datetime.date.today().isoformat()

    conn = get_db()

    # One row per cluster: best entry + count of all entries in that cluster today
    rows = conn.execute(
        """
        WITH today_entries AS (
            SELECT e.id, e.title, e.link, e.published, e.summary,
                   f.title AS feed_title,
                   et.cluster_id, et.score
            FROM entries e
            JOIN feeds f      ON f.id  = e.feed_id
            JOIN entry_topics et ON et.entry_id = e.id
            WHERE DATE(e.published) = ?
        ),
        cluster_counts AS (
            SELECT cluster_id, COUNT(*) AS cnt
            FROM today_entries
            GROUP BY cluster_id
        ),
        best_per_cluster AS (
            SELECT te.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY te.cluster_id
                       ORDER BY te.score DESC, te.published DESC
                   ) AS rn
            FROM today_entries te
        )
        SELECT
            tc.label,
            b.title      AS headline,
            b.link,
            b.feed_title,
            b.published,
            cc.cnt       AS total_count
        FROM best_per_cluster b
        JOIN cluster_counts cc    ON cc.cluster_id = b.cluster_id
        JOIN topic_clusters tc    ON tc.id         = b.cluster_id
        WHERE b.rn = 1
        ORDER BY cc.cnt DESC, b.score DESC
        """,
        (target,),
    ).fetchall()
    conn.close()

    bullets = [
        DigestBullet(
            label=r["label"] or "Topic",
            headline=r["headline"] or "(no title)",
            link=r["link"],
            feed_title=r["feed_title"],
            published=r["published"],
            extra_count=max(0, r["total_count"] - 1),
        )
        for r in rows
    ]
    return DigestOut(date=target, bullets=bullets)


@router.post("/api/digest/llm", response_model=LlmDigestOut)
def generate_llm_digest(date: Optional[str] = None):
    """
    Call the local ollama instance to produce a prose bullet digest for the
    given date (YYYY-MM-DD, defaults to today). The result is cached in
    daily_digests; calling again on the same date returns the cached version
    unless it was deleted first via DELETE /api/digest/llm.
    """
    import datetime
    import urllib.request
    import urllib.error
    import json as _json

    target = date or datetime.date.today().isoformat()

    ollama_url   = get_setting("ollama_url")   or "http://localhost:11434"
    ollama_model = get_setting("ollama_model") or "llama3.2:1b"

    # Return cached result if available
    conn = get_db()
    cached_row = conn.execute(
        "SELECT summary, model FROM daily_digests WHERE date = ?", (target,)
    ).fetchone()
    conn.close()
    if cached_row:
        return LlmDigestOut(
            date=target,
            summary=cached_row["summary"],
            model=cached_row["model"] or ollama_model,
            cached=True,
        )

    # Build context from today's cluster headlines (same query as get_digest)
    conn = get_db()
    rows = conn.execute(
        """
        WITH today_entries AS (
            SELECT e.title, e.link,
                   f.title AS feed_title,
                   et.cluster_id, et.score
            FROM entries e
            JOIN feeds f         ON f.id  = e.feed_id
            JOIN entry_topics et ON et.entry_id = e.id
            WHERE DATE(e.published) = ?
        ),
        cluster_counts AS (
            SELECT cluster_id, COUNT(*) AS cnt
            FROM today_entries GROUP BY cluster_id
        ),
        best_per_cluster AS (
            SELECT te.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY te.cluster_id
                       ORDER BY te.score DESC
                   ) AS rn
            FROM today_entries te
        )
        SELECT tc.label, b.title AS headline, b.feed_title, cc.cnt
        FROM best_per_cluster b
        JOIN cluster_counts cc ON cc.cluster_id = b.cluster_id
        JOIN topic_clusters tc ON tc.id         = b.cluster_id
        WHERE b.rn = 1
        ORDER BY cc.cnt DESC, b.score DESC
        """,
        (target,),
    ).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No clustered articles found for {target}. "
                   "Refresh feeds and run a re-cluster first.",
        )

    # Build the prompt
    article_lines = "\n".join(
        f"- [{r['label']}] {r['headline']} ({r['feed_title'] or 'unknown source'})"
        + (f" — and {r['cnt'] - 1} more similar" if r["cnt"] > 1 else "")
        for r in rows
    )
    prompt = (
        "You are a neutral, concise news editor. "
        "Below are today's top news headlines grouped by topic.\n\n"
        f"{article_lines}\n\n"
        "Write a bullet-point digest that:\n"
        "• Groups similar stories into one bullet\n"
        "• Uses neutral, factual language\n"
        "• Covers all major stories without repetition\n"
        "• Orders bullets by importance (most significant first)\n"
        "• Uses as many bullets as needed — no more, no fewer\n\n"
        "Respond with only the bullet list. Each bullet must start with '• '."
    )

    payload = _json.dumps({
        "model": ollama_model,
        "prompt": prompt,
        "stream": False,
    }).encode()

    api_endpoint = ollama_url.rstrip("/") + "/api/generate"
    req = urllib.request.Request(
        api_endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
        if not raw:
            raise HTTPException(status_code=502, detail="ollama returned an empty response body.")
        body = _json.loads(raw)
        summary = body.get("response", "").strip()
    except HTTPException:
        raise
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not reach ollama at {api_endpoint}: {exc.reason}",
        ) from exc
    except _json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"ollama returned an invalid JSON response: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not summary:
        raise HTTPException(status_code=502, detail="ollama returned an empty response.")

    # Cache the result
    now = datetime.datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO daily_digests (date, summary, model, created_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(date) DO UPDATE SET summary=excluded.summary, model=excluded.model, created_at=excluded.created_at",
        (target, summary, ollama_model, now),
    )
    conn.commit()
    conn.close()

    return LlmDigestOut(date=target, summary=summary, model=ollama_model, cached=False)


@router.delete("/api/digest/llm", status_code=204)
def clear_llm_digest(date: Optional[str] = None):
    """Delete the cached LLM digest for a date so the next POST regenerates it."""
    import datetime
    target = date or datetime.date.today().isoformat()
    conn = get_db()
    conn.execute("DELETE FROM daily_digests WHERE date = ?", (target,))
    conn.commit()
    conn.close()


@router.post("/api/recluster", status_code=202)
def trigger_recluster():
    """
    Launch the topic clustering pipeline in a child process so that an
    OOM-kill on the Pi only terminates the child, not the web server.
    Returns immediately — the child writes progress into cluster_jobs;
    poll /api/recluster/status for updates.
    """
    import subprocess
    import sys
    from scripts.cluster_topics import start_job, finish_job

    job_id = start_job()

    cmd = [sys.executable, "-m", "scripts.cluster_topics", "--job-id", str(job_id)]
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        finish_job(job_id, success=False, error_log=str(exc))
        logger.exception("Failed to launch clustering child")
        raise HTTPException(status_code=500, detail=f"Failed to start clustering process: {exc}") from exc

    return {"status": "ok", "job_id": job_id, "message": "Re-clustering started."}


@router.get("/api/recluster/status")
def recluster_status():
    """Return the most recent clustering job's status."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, status, step, progress, total, started_at, finished_at, error_log "
        "FROM cluster_jobs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return {"status": "none"}
    return dict(row)


# ---------------------------------------------------------------------------
# ollama model management
# ---------------------------------------------------------------------------

@router.get("/api/ollama/status")
def ollama_model_status():
    """Check whether ollama is reachable and the configured model is available."""
    import urllib.request
    import urllib.error
    import json as _json

    ollama_url   = get_setting("ollama_url")   or "http://localhost:11434"
    ollama_model = get_setting("ollama_model") or "llama3.2:1b"

    try:
        req = urllib.request.Request(ollama_url.rstrip("/") + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = _json.loads(resp.read().decode())
        models = [m["name"] for m in body.get("models", [])]
        model_available = any(
            m == ollama_model or m.split(":")[0] == ollama_model.split(":")[0]
            for m in models
        )
        return {
            "reachable": True,
            "model": ollama_model,
            "model_available": model_available,
            "available_models": models,
        }
    except urllib.error.URLError as exc:
        return {"reachable": False, "model": ollama_model, "model_available": False, "error": str(exc.reason)}
    except Exception as exc:
        return {"reachable": False, "model": ollama_model, "model_available": False, "error": str(exc)}


@router.post("/api/ollama/pull", status_code=202)
def pull_ollama_model():
    """Start a background thread to pull (or re-pull) the configured ollama model."""
    import threading

    global _pull_state
    if _pull_state.get("status") == "pulling":
        raise HTTPException(status_code=409, detail="A pull is already in progress.")

    ollama_url   = get_setting("ollama_url")   or "http://localhost:11434"
    ollama_model = get_setting("ollama_model") or "llama3.2:1b"

    t = threading.Thread(target=_do_pull, args=(ollama_url, ollama_model), daemon=True)
    t.start()
    return {"status": "ok", "message": f"Pulling {ollama_model}…"}


@router.get("/api/ollama/pull/status")
def ollama_pull_status():
    """Return the current model pull progress."""
    return dict(_pull_state)
