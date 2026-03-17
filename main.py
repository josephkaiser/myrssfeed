import logging
import logging.handlers
import os
import json
import re
import sqlite3
import threading
import urllib.parse
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from typing import Optional

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl


# ── Logging ───────────────────────────────────────────────────────────────────

_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(_LOG_DIR, "myrssfeed.log")

_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)
_fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5)
_fh.setFormatter(_fmt)
_root.addHandler(_fh)

logger = logging.getLogger(__name__)


# ── Database ──────────────────────────────────────────────────────────────────

DB_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), "feeds", "rss.db"))

DEFAULTS: dict[str, str] = {
    "retention_days": "90",
    "theme": "system",
    # Maximum number of articles to show on the main page.
    # Stored in the DB but also exposed here so it can be managed via /api/settings.
    "max_entries": "1000",
}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS feeds (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            url   TEXT UNIQUE NOT NULL,
            title TEXT,
            color TEXT
        );

        CREATE TABLE IF NOT EXISTS entries (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id       INTEGER NOT NULL,
            title         TEXT,
            link          TEXT,
            published     TEXT,
            summary       TEXT,
            thumbnail_url TEXT,
            read          INTEGER DEFAULT 0,
            liked         INTEGER DEFAULT 0,
            UNIQUE(feed_id, link),
            FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_catalog (
            url         TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'User Added',
            description TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.commit()
    # Migrate existing databases
    entry_cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}
    for col, definition in [
        ("thumbnail_url", "TEXT"),
        ("read", "INTEGER DEFAULT 0"),
        ("liked", "INTEGER DEFAULT 0"),
        ("og_title", "TEXT"),
        ("og_description", "TEXT"),
        ("og_image_url", "TEXT"),
        ("full_content", "TEXT"),
    ]:
        if col not in entry_cols:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {col} {definition}")
    feed_cols = {r[1] for r in conn.execute("PRAGMA table_info(feeds)").fetchall()}
    if "color" not in feed_cols:
        conn.execute("ALTER TABLE feeds ADD COLUMN color TEXT")
    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    env_val = os.environ.get(f"MYRSSFEED_{key.upper()}")
    if env_val is not None:
        return env_val
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else DEFAULTS.get(key, "")


def set_setting(key: str, value: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


# ── Pipeline / scheduler ──────────────────────────────────────────────────────

_pipeline_lock = threading.Lock()
_pipeline_running = False


def is_pipeline_running() -> bool:
    return _pipeline_running


def _do_pipeline():
    global _pipeline_running
    logger.info("Pipeline starting.")
    try:
        from scripts.compile_feed import run_compile_feed
        run_compile_feed()
    except Exception:
        logger.exception("Pipeline: compile_feed failed.")
    finally:
        _pipeline_running = False
        _pipeline_lock.release()
    logger.info("Pipeline complete.")


def run_pipeline():
    global _pipeline_running
    if not _pipeline_lock.acquire(blocking=False):
        logger.info("Pipeline already running — skipping.")
        return
    _pipeline_running = True
    _do_pipeline()


def run_pipeline_async() -> bool:
    if _pipeline_running:
        return False
    t = threading.Thread(target=run_pipeline, daemon=True, name="pipeline")
    t.start()
    return True


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_pipeline",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler: daily feed fetch at 06:00.")
    return scheduler


# ── Schemas ───────────────────────────────────────────────────────────────────

class FeedCreate(BaseModel):
    url: HttpUrl
    title: Optional[str] = None


class FeedOut(BaseModel):
    id: int
    url: str
    title: Optional[str]
    color: Optional[str] = None


class EntryOut(BaseModel):
    id: int
    feed_id: int
    feed_title: Optional[str]
    title: Optional[str]
    link: Optional[str]
    published: Optional[str]
    summary: Optional[str]
    read: int = 0
    liked: int = 0
    thumbnail_url: Optional[str] = None


class SettingsUpdate(BaseModel):
    retention_days: Optional[str] = None
    theme: Optional[str] = None
    max_entries: Optional[str] = None


class DetectRequest(BaseModel):
    url: str


# ── Catalog ───────────────────────────────────────────────────────────────────

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "data", "feed_catalog.json")
try:
    with open(_CATALOG_PATH, "r", encoding="utf-8") as _f:
        _FEED_CATALOG = json.load(_f)
except Exception:
    _FEED_CATALOG = []

_STATIC_CATALOG_URLS = {f["url"] for f in _FEED_CATALOG}


def _add_to_user_catalog(url: str, name: str) -> None:
    """Persist a feed in the user catalog so it appears on the discover page."""
    if url in _STATIC_CATALOG_URLS:
        return
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO user_catalog (url, name) VALUES (?, ?)",
        (url, name or url),
    )
    conn.commit()
    conn.close()


def _get_full_catalog() -> list[dict]:
    """Merge the static catalog with user-added entries."""
    conn = get_db()
    rows = conn.execute("SELECT url, name, category, description FROM user_catalog").fetchall()
    conn.close()
    static_urls = _STATIC_CATALOG_URLS
    extras = [
        {"url": r["url"], "name": r["name"], "category": r["category"], "description": r["description"]}
        for r in rows if r["url"] not in static_urls
    ]
    return _FEED_CATALOG + extras


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("myRSSfeed started.")
    yield
    scheduler.shutdown(wait=False)
    logger.info("myRSSfeed stopped.")


app = FastAPI(title="myRSSfeed", lifespan=lifespan)

_static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

_templates_dir = os.path.join(os.path.dirname(__file__), "web", "templates")
templates = Jinja2Templates(directory=_templates_dir)


# ── UI routes ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: Optional[str] = None, feed_id: Optional[int] = None):
    conn = get_db()
    feeds_rows = conn.execute("SELECT id, url, title, color FROM feeds ORDER BY title").fetchall()
    feeds = [dict(f) for f in feeds_rows]

    feed_map = {}
    for f in feeds:
        parsed = urllib.parse.urlparse(f["url"])
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
               COALESCE(e.liked, 0) AS liked
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
    conn.close()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "feeds": feeds,
        "feed_map": feed_map,
        "entries": [dict(e) for e in entries],
        "q": q or "",
        "active_feed_id": feed_id,
    })


@app.get("/article/{entry_id}", response_class=HTMLResponse)
def article_page(request: Request, entry_id: int):
    conn = get_db()
    row = conn.execute(
        """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               e.og_title, e.og_description, e.og_image_url, e.full_content,
               COALESCE(e.read, 0) AS read
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Article not found.")
    entry = dict(row)
    feed_row = conn.execute("SELECT id, url, title, color FROM feeds WHERE id = ?", (entry["feed_id"],)).fetchone()
    conn.execute("UPDATE entries SET read = 1 WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()

    if feed_row:
        feed_map = _build_feed_map([dict(feed_row)])
    else:
        feed_map = {entry["feed_id"]: {"title": entry["feed_title"], "domain": "", "color": None}}
    return templates.TemplateResponse("article.html", {
        "request": request,
        "entry": entry,
        "feed_map": feed_map,
    })


def _build_feed_map(feeds: list[dict]) -> dict:
    out = {}
    for f in feeds:
        parsed = urllib.parse.urlparse(f["url"])
        out[f["id"]] = {
            "title": f.get("title"),
            "url": f.get("url"),
            "domain": parsed.netloc,
            "color": f.get("color"),
        }
    return out


@app.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request):
    conn = get_db()
    rows = conn.execute("SELECT id, url, title, color FROM feeds ORDER BY title").fetchall()
    conn.close()
    feeds = [dict(r) for r in rows]
    feed_map = _build_feed_map(feeds)
    return templates.TemplateResponse(
        "feeds.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "feeds_json": json.dumps(feeds),
            "q": "",
            "active_feed_id": None,
        },
    )


@app.get("/discover", response_class=HTMLResponse)
def discover_page(request: Request):
    conn = get_db()
    rows = conn.execute("SELECT id, url, title, color FROM feeds ORDER BY title").fetchall()
    conn.close()
    feeds = [dict(r) for r in rows]
    feed_map = _build_feed_map(feeds)
    subscribed = [r["url"] for r in rows]
    return templates.TemplateResponse(
        "discover.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "catalog_json": json.dumps(_get_full_catalog()),
            "subscribed_json": json.dumps(subscribed),
            "q": "",
            "active_feed_id": None,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    conn = get_db()
    rows = conn.execute("SELECT id, url, title, color FROM feeds ORDER BY title").fetchall()
    conn.close()
    feeds = [dict(r) for r in rows]
    feed_map = _build_feed_map(feeds)
    current = {key: get_setting(key) for key in DEFAULTS}
    if "max_entries" not in current:
        current["max_entries"] = get_setting("max_entries")

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "feeds": feeds,
            "feed_map": feed_map,
            "settings": current,
            "q": "",
            "active_feed_id": None,
        },
    )


# ── Feed API ──────────────────────────────────────────────────────────────────

@app.get("/api/feeds", response_model=list[FeedOut])
def list_feeds():
    conn = get_db()
    rows = conn.execute("SELECT id, url, title, color FROM feeds ORDER BY title").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/feeds", response_model=FeedOut, status_code=201)
def add_feed(feed: FeedCreate):
    conn = get_db()
    try:
        row = conn.execute(
            "INSERT INTO feeds (url, title) VALUES (?, ?) RETURNING id, url, title, color",
            (str(feed.url), feed.title),
        ).fetchone()
        conn.commit()
    except Exception as exc:
        conn.close()
        raise HTTPException(status_code=409, detail="Feed URL already exists.") from exc
    conn.close()
    _add_to_user_catalog(str(feed.url), feed.title or str(feed.url))
    return dict(row)


@app.delete("/api/feeds/{feed_id}", status_code=204)
def delete_feed(feed_id: int):
    conn = get_db()
    conn.execute("DELETE FROM entries WHERE feed_id = ?", (feed_id,))
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()


# ── Entries API ───────────────────────────────────────────────────────────────

@app.get("/api/entries", response_model=list[EntryOut])
def list_entries(q: Optional[str] = None, feed_id: Optional[int] = None, limit: int = 100):
    conn = get_db()
    query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked
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


@app.post("/api/entries/{entry_id}/read", status_code=200)
def mark_read(entry_id: int):
    conn = get_db()
    conn.execute("UPDATE entries SET read = 1 WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/entries/{entry_id}/like", status_code=200)
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


# ── Settings API ──────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    return {key: get_setting(key) for key in DEFAULTS}


@app.post("/api/settings")
def update_settings(payload: SettingsUpdate):
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        set_setting(key, str(value))
    return {key: get_setting(key) for key in DEFAULTS}


# ── Refresh API ───────────────────────────────────────────────────────────────

@app.post("/api/refresh", status_code=202)
def trigger_refresh():
    if is_pipeline_running():
        return {"status": "running", "message": "Pipeline already in progress."}
    started = run_pipeline_async()
    if not started:
        return {"status": "running", "message": "Pipeline already in progress."}
    return {"status": "started", "message": "Pipeline started in background."}


# ── Search API ────────────────────────────────────────────────────────────────

@app.get("/api/search")
def live_search(q: Optional[str] = None, limit: int = 8):
    if not q or not q.strip():
        return {"suggestions": [], "entries": []}
    q = q.strip()
    conn = get_db()
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
            for word in re.findall(r"[A-Za-z']+", row["title"]):
                wl = word.lower()
                if wl.startswith(last_word.lower()) and wl != last_word.lower() and len(wl) > len(last_word) and wl not in seen:
                    seen.add(wl)
                    suggestions.append(word)
                    if len(suggestions) >= 8:
                        break
            if len(suggestions) >= 8:
                break
    conn.close()
    return {"suggestions": suggestions, "entries": [dict(r) for r in entry_rows]}


# ── Discover API ──────────────────────────────────────────────────────────────

@app.post("/api/discover/detect")
def detect_feeds(payload: DetectRequest):
    import socket
    raw_url = payload.url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.netloc:
        raise HTTPException(status_code=422, detail="Invalid URL.")
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
                    self.feeds.append({"name": d.get("title", ""), "url": href})

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

    if any(t in content_type for t in ("rss", "atom", "xml")):
        title = ""
        m = re.search(r"<title[^>]*>([^<]{1,120})</title>", body, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
        return {"feeds": [{"name": title or "Feed", "url": raw_url}]}

    parser = LinkParser()
    parser.feed(body)
    feeds = []
    seen = set()
    for f in parser.feeds:
        url = urllib.parse.urljoin(raw_url, f["url"])
        if url not in seen:
            seen.add(url)
            feeds.append({"name": f["name"], "url": url})

    if not feeds:
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in ["/rss", "/feed", "/rss.xml", "/atom.xml", "/feed.xml", "/blog/feed", "/blog/rss"]:
            probe_url = base + path
            try:
                probe_req = urllib.request.Request(probe_url, headers=headers, method="HEAD")
                with urllib.request.urlopen(probe_req, timeout=4) as r:
                    ct = r.headers.get("Content-Type", "")
                    if any(t in ct for t in ("rss", "atom", "xml")) and probe_url not in seen:
                        seen.add(probe_url)
                        feeds.append({"name": "", "url": probe_url})
            except Exception:
                continue

    return {"feeds": feeds[:8]}


# ── Logs API ──────────────────────────────────────────────────────────────────

@app.get("/api/logs")
def get_logs(lines: int = 100):
    if not os.path.exists(LOG_FILE):
        return {"lines": []}
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return {"lines": [l.rstrip("\n") for l in all_lines[-lines:]]}
    except Exception as exc:
        logger.warning("Could not read log file: %s", exc)
        return {"lines": []}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
