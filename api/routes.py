import json
import logging
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from typing import Optional

from utils.helpers import get_db, get_setting, set_setting, DEFAULTS
from api.schemas import FeedCreate, FeedOut, EntryOut, SettingsUpdate, DigestOut, VizEntryOut, VizThemeOut, DeviceCreate, DeviceOut, DetectRequest
from scripts.compile_feed import run_compile_feed
from scripts.scraper import run_scraper_async, is_scraper_running
from scripts.wordrank import run_wordrank

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "feed_catalog.json")
try:
    with open(_CATALOG_PATH, "r", encoding="utf-8") as _f:
        _FEED_CATALOG = json.load(_f)
except Exception:
    _FEED_CATALOG = []

MAX_DEVICES = 5

logger = logging.getLogger(__name__)

router = APIRouter()

_templates_dir = os.path.join(os.path.dirname(__file__), "..", "web", "templates")
templates = Jinja2Templates(directory=_templates_dir)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@router.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request):
    conn = get_db()
    rows = conn.execute("SELECT id, url, title FROM feeds ORDER BY title").fetchall()
    conn.close()
    return templates.TemplateResponse(
        "feeds.html",
        {"request": request, "feeds_json": json.dumps([dict(r) for r in rows])},
    )


@router.get("/devices", response_class=HTMLResponse)
def devices_page(request: Request):
    conn = get_db()
    rows = conn.execute("SELECT id, name, added_at FROM devices ORDER BY added_at").fetchall()
    conn.close()
    return templates.TemplateResponse(
        "device.html",
        {"request": request, "devices": [dict(r) for r in rows], "max_devices": MAX_DEVICES},
    )



@router.get("/api/devices", response_model=list[DeviceOut])
def list_devices():
    conn = get_db()
    rows = conn.execute("SELECT id, name, added_at FROM devices ORDER BY added_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/devices", response_model=DeviceOut, status_code=201)
def add_device(device: DeviceCreate):
    name = device.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Device name cannot be empty.")
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    if count >= MAX_DEVICES:
        conn.close()
        raise HTTPException(status_code=409, detail=f"Maximum of {MAX_DEVICES} devices reached. Remove one first.")
    row = conn.execute(
        "INSERT INTO devices (name) VALUES (?) RETURNING id, name, added_at",
        (name,),
    ).fetchone()
    conn.commit()
    conn.close()
    return dict(row)


@router.delete("/api/devices/{device_id}", status_code=204)
def remove_device(device_id: int):
    conn = get_db()
    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    conn.commit()
    conn.close()


@router.get("/discover", response_class=HTMLResponse)
def discover_page(request: Request):
    conn = get_db()
    rows = conn.execute("SELECT url FROM feeds").fetchall()
    conn.close()
    subscribed = [r["url"] for r in rows]
    return templates.TemplateResponse(
        "discover.html",
        {
            "request": request,
            "catalog_json": json.dumps(_FEED_CATALOG),
            "subscribed_json": json.dumps(subscribed),
        },
    )


@router.post("/api/discover/detect")
def detect_feeds(payload: DetectRequest):
    """Fetch a URL and return any RSS/Atom feeds found on the page."""
    import urllib.request
    import urllib.error
    import urllib.parse
    from html.parser import HTMLParser

    raw_url = payload.url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.netloc:
        raise HTTPException(status_code=422, detail="Invalid URL.")

    # Reject private/loopback addresses from being fetched
    import socket
    try:
        addr = socket.getaddrinfo(parsed.hostname, None)[0][4][0]
        if any(addr.startswith(p) for p in ("127.", "10.", "192.168.", "169.254.", "::1")):
            raise HTTPException(status_code=422, detail="Private network addresses are not allowed.")
    except HTTPException:
        raise
    except Exception:
        pass

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.feeds = []
        def handle_starttag(self, tag, attrs):
            if tag.lower() != "link":
                return
            d = dict(attrs)
            t = d.get("type", "").lower()
            if t in ("application/rss+xml", "application/atom+xml", "application/rdf+xml"):
                href = d.get("href", "")
                if href:
                    title = d.get("title", "")
                    self.feeds.append({"name": title, "url": href})

    headers = {"User-Agent": "myRSSfeed/1.0 (RSS discovery)"}
    req = urllib.request.Request(raw_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read(512 * 1024).decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=422, detail=f"Could not reach URL: {exc.reason}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Request failed: {exc}")

    # If the URL itself is an RSS/Atom feed, return it directly
    if any(t in content_type for t in ("rss", "atom", "xml")):
        title = ""
        import re
        m = re.search(r"<title[^>]*>([^<]{1,120})</title>", body, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
        return {"feeds": [{"name": title or "Feed", "url": raw_url}]}

    parser = LinkParser()
    parser.feed(body)

    # Resolve relative URLs
    feeds = []
    seen = set()
    for f in parser.feeds:
        url = urllib.parse.urljoin(raw_url, f["url"])
        if url not in seen:
            seen.add(url)
            feeds.append({"name": f["name"], "url": url})

    # If nothing found, probe common paths
    if not feeds:
        base = f"{parsed.scheme}://{parsed.netloc}"
        common = ["/rss", "/feed", "/rss.xml", "/atom.xml", "/feed.xml", "/blog/feed", "/blog/rss"]
        for path in common:
            probe_url = base + path
            try:
                probe_req = urllib.request.Request(probe_url, headers=headers, method="HEAD")
                with urllib.request.urlopen(probe_req, timeout=4) as r:
                    ct = r.headers.get("Content-Type", "")
                    if any(t in ct for t in ("rss", "atom", "xml")):
                        if probe_url not in seen:
                            seen.add(probe_url)
                            feeds.append({"name": "", "url": probe_url})
            except Exception:
                continue

    return {"feeds": feeds[:8]}


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


def _compute_trending(entries: list[dict], limit: int = 8) -> list[dict]:
    """
    Build a small "trending" set that:
    - favours recency (entries are already newest-first)
    - encourages diversity of source (per-feed cap)
    - uses the existing score field to prefer more unique content
    """
    if not entries:
        return []

    # Combine recency (position in list) and score into one ranking value.
    # Newest entries appear first in `entries`.
    n = len(entries)
    ranked = []
    for idx, e in enumerate(entries):
        recency_weight = (n - idx) / n  # 1.0 for newest, down to ~0
        score = float(e.get("score") or 0.0)
        combined = 0.7 * recency_weight + 0.3 * score
        ranked.append((combined, e))

    ranked.sort(key=lambda t: t[0], reverse=True)

    # Greedy pick with per-feed cap to keep sources diverse.
    per_feed_cap = 2
    feed_counts: dict[int, int] = {}
    trending: list[dict] = []
    for _, e in ranked:
        feed_id = int(e.get("feed_id") or 0)
        if feed_id:
            if feed_counts.get(feed_id, 0) >= per_feed_cap:
                continue
            feed_counts[feed_id] = feed_counts.get(feed_id, 0) + 1
        trending.append(e)
        if len(trending) >= limit:
            break

    return trending


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

    try:
        max_entries = int(get_setting("max_entries") or "1000")
    except (ValueError, TypeError):
        max_entries = 1000
    if max_entries <= 0:
        max_entries = 1000

    query += " ORDER BY e.published DESC LIMIT ?"
    params.append(max_entries)
    entries = conn.execute(query, params).fetchall()

    entries_list = [dict(e) for e in entries]

    # Compute trending from recent global entries (not filtered),
    # so the sidebar always has something interesting.
    trending_query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        ORDER BY e.published DESC
        LIMIT 200
    """
    trending_rows = conn.execute(trending_query).fetchall()
    conn.close()

    trending_list = [dict(e) for e in trending_rows]
    trending = _compute_trending(trending_list)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "entries": entries_list,
            "trending": trending,
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
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               e.og_title,
               e.og_description,
               e.og_image_url
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
    # If scheduler settings changed, ask the running scheduler to reconfigure
    # itself based on the new values. Safe to call even if scheduler is not yet started.
    try:
        from scripts.scheduler import reconfigure_scheduler

        reconfigure_scheduler()
    except Exception:
        logger.exception("Failed to reconfigure scheduler after settings update.")
    return {key: get_setting(key) for key in DEFAULTS}


# ---------------------------------------------------------------------------
# Manual trigger — runs the full pipeline
# ---------------------------------------------------------------------------

@router.post("/api/refresh", status_code=202)
def trigger_refresh():
    """Kick off the full daily pipeline in the background."""
    from scheduler import run_pipeline_async, is_pipeline_running
    if is_pipeline_running():
        return {"status": "running", "message": "Pipeline already in progress."}
    started = run_pipeline_async()
    if not started:
        return {"status": "running", "message": "Pipeline already in progress."}
    return {"status": "started", "message": "Pipeline started in background."}


@router.post("/api/scrape", status_code=202)
def trigger_scrape():
    """Kick off a background job to scrape/enrich existing entries."""
    if is_scraper_running():
        return {"status": "running", "message": "Scraper already in progress."}
    started = run_scraper_async()
    if not started:
        return {"status": "running", "message": "Scraper already in progress."}
    return {"status": "started", "message": "Scrape job started in background."}


@router.get("/api/scrape/status")
def get_scrape_status():
    """
    Return the current status of the manual enrich/scrape job.

    Used by the settings page to show a simple status light:
    - running: job currently in progress
    - success: last completed run had no errors
    - error:   last completed run encountered errors
    - never:   no runs have been recorded yet
    """
    from scripts.scraper import is_scraper_running

    running = is_scraper_running()
    last_status = get_setting("scrape_last_status") or "never"
    return {"running": running, "last_status": last_status}


@router.get("/api/refresh/status")
def get_refresh_status():
    """
    Return the current pipeline/job status for the manual/automatic refresh.

    Used by the settings page to show a simple status light:
    - running: job currently in progress
    - success: last completed run had no errors
    - error:   last completed run encountered errors
    - never:   no runs have been recorded yet
    """
    from scheduler import is_pipeline_running

    running = is_pipeline_running()
    last_status = get_setting("pipeline_last_status") or "never"
    return {"running": running, "last_status": last_status}


@router.post("/api/wordrank", status_code=202)
def trigger_wordrank():
    """Run WordRank scoring synchronously and report basic status."""
    try:
        run_wordrank()
    except Exception as exc:
        logger.exception("WordRank job failed: %s", exc)
        return {"status": "error", "message": "WordRank failed (see logs)."}
    return {"status": "success", "message": "WordRank completed."}


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
