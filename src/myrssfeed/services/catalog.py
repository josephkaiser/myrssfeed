import json
import sqlite3
import urllib.parse
from typing import Callable, Optional

from myrssfeed.paths import CATALOG_PATH


try:
    with open(CATALOG_PATH, "r", encoding="utf-8") as catalog_file:
        FEED_CATALOG = json.load(catalog_file)
except Exception:
    FEED_CATALOG = []


STATIC_CATALOG_URLS = {item["url"] for item in FEED_CATALOG}


def seed_catalogue_feeds(conn: sqlite3.Connection) -> None:
    """Ensure the static catalogue exists in the service DB."""
    if not FEED_CATALOG:
        return

    for item in FEED_CATALOG:
        url = item.get("url") or ""
        name = (item.get("name") or url).strip()
        category = (item.get("category") or "").strip() or None
        if not url:
            continue
        try:
            conn.execute(
                """
                INSERT INTO feeds (url, title, subscribed, category)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(url) DO NOTHING
                """,
                (url, name or None, category),
            )
        except Exception:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO feeds (url, title, subscribed) VALUES (?, ?, 0)",
                    (url, name or None),
                )
            except Exception:
                pass
    conn.commit()


def add_to_user_catalog(
    get_db: Callable[[], sqlite3.Connection],
    url: str,
    name: str,
) -> None:
    """Persist a feed in the user catalog so it appears on Discover."""
    if url in STATIC_CATALOG_URLS:
        return
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_catalog (url, name) VALUES (?, ?)",
            (url, name or url),
        )
        conn.commit()
    finally:
        conn.close()


def get_full_catalog(get_db: Callable[[], sqlite3.Connection]) -> list[dict]:
    """Merge the static catalog with user-added entries."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT url, name, category, description FROM user_catalog"
        ).fetchall()
    finally:
        conn.close()

    static_items = [{**item, "removable": False} for item in FEED_CATALOG]
    extras = [
        {
            "url": row["url"],
            "name": row["name"],
            "category": row["category"],
            "description": row["description"],
            "removable": True,
        }
        for row in rows
        if row["url"] not in STATIC_CATALOG_URLS
    ]
    return static_items + extras


def feed_host(feed_url: Optional[str]) -> str:
    parsed = urllib.parse.urlparse(feed_url or "")
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return ""
    host = (parsed.hostname or parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def build_feed_map(feeds: list[dict]) -> dict:
    return {
        feed["id"]: {
            "title": feed.get("title"),
            "url": feed.get("url"),
            "domain": feed_host(feed.get("url")),
            "color": feed.get("color"),
        }
        for feed in feeds
    }
