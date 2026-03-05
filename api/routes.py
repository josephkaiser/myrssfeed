import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import os

from utils.helpers import get_db, get_setting, set_setting, DEFAULTS
from api.schemas import FeedCreate, FeedOut, EntryOut, SettingsUpdate, DigestOut, VizEntryOut, VizThemeOut
from scripts.compile_feed import run_compile_feed

logger = logging.getLogger(__name__)

router = APIRouter()

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


@router.get("/viz", response_class=HTMLResponse)
def viz_page(request: Request):
    return templates.TemplateResponse("viz.html", {"request": request})


@router.get("/digest", response_class=HTMLResponse)
def digest_page(request: Request):
    return templates.TemplateResponse("digest.html", {"request": request})


@router.get("/", response_class=HTMLResponse)
def index(request: Request, q: Optional[str] = None, feed_id: Optional[int] = None):
    conn = get_db()
    feeds_rows = conn.execute("SELECT id, url, title, color FROM feeds ORDER BY title").fetchall()
    feeds = [dict(f) for f in feeds_rows]

    # Build feed_map for favicon and color lookup in the template
    from urllib.parse import urlparse
    feed_map = {}
    for f in feeds:
        parsed = urlparse(f["url"])
        feed_map[f["id"]] = {
            "title": f["title"],
            "url": f["url"],
            "domain": parsed.netloc,
            "color": f["color"],
        }

    query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score
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
            "feeds": feeds,
            "feed_map": feed_map,
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
# Manual trigger — runs the full pipeline
# ---------------------------------------------------------------------------

@router.post("/api/refresh", status_code=202)
def trigger_refresh():
    """Manually kick off the full daily pipeline."""
    from scheduler import run_pipeline
    try:
        run_pipeline()
    except Exception as exc:
        logger.exception("Manual refresh failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "message": "Pipeline complete."}


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
# Entry interactions
# ---------------------------------------------------------------------------

@router.post("/api/entries/{entry_id}/read", status_code=200)
def mark_read(entry_id: int):
    conn = get_db()
    conn.execute("UPDATE entries SET read = 1 WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.post("/api/entries/{entry_id}/like", status_code=200)
def toggle_like(entry_id: int):
    conn = get_db()
    row = conn.execute("SELECT COALESCE(liked, 0) AS liked FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Entry not found.")
    new_liked = 0 if row["liked"] else 1
    conn.execute("UPDATE entries SET liked = ? WHERE id = ?", (new_liked, entry_id))
    conn.commit()
    conn.close()
    return {"liked": bool(new_liked)}


# ---------------------------------------------------------------------------
# Visualization data
# ---------------------------------------------------------------------------

@router.get("/api/viz")
def get_viz():
    conn = get_db()
    entry_rows = conn.execute(
        "SELECT id, feed_id, title, viz_x, viz_y FROM entries WHERE viz_x IS NOT NULL"
    ).fetchall()
    theme_rows = []
    try:
        theme_rows = conn.execute(
            "SELECT label, centroid_x, centroid_y, size FROM viz_themes"
        ).fetchall()
    except Exception:
        pass
    conn.close()
    return {
        "entries": [dict(r) for r in entry_rows],
        "themes": [dict(r) for r in theme_rows],
    }


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

@router.get("/api/digest")
def get_digest():
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT date, content, model, created_at FROM daily_digests ORDER BY date DESC LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No digest available yet.")
    return dict(row)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@router.get("/api/logs")
def get_logs(lines: int = 100):
    import main as _main_module
    log_file = getattr(_main_module, "LOG_FILE", None)
    if not log_file or not os.path.exists(log_file):
        return {"lines": []}
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return {"lines": [l.rstrip("\n") for l in all_lines[-lines:]]}
    except Exception as exc:
        logger.warning("Could not read log file: %s", exc)
        return {"lines": []}


