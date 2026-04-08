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
STARTER_CATALOG_URLS = frozenset(
    {
        "https://news.ycombinator.com/rss",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://www.technologyreview.com/feed/",
        "https://feeds.reuters.com/reuters/worldNews",
        "https://www.nasa.gov/news-release/feed/",
    }
)
STARTER_FEEDS_INITIALIZED_KEY = "starter_feeds_initialized"

CANONICAL_CATEGORY_ALIASES = {
    "ai/ml": "AI/ML",
    "aiml": "AI/ML",
    "ai & ml": "AI/ML",
    "artificial intelligence & machine learning": "AI/ML",
}


def normalize_catalog_category(category: Optional[str]) -> Optional[str]:
    label = str(category or "").strip()
    if not label:
        return None
    return CANONICAL_CATEGORY_ALIASES.get(label.lower(), label)


def normalize_catalog_categories_in_db(conn: sqlite3.Connection) -> None:
    for raw_label, canonical_label in CANONICAL_CATEGORY_ALIASES.items():
        conn.execute(
            "UPDATE feeds SET category = ? WHERE LOWER(TRIM(COALESCE(category, ''))) = ?",
            (canonical_label, raw_label),
        )
        conn.execute(
            "UPDATE user_catalog SET category = ? WHERE LOWER(TRIM(COALESCE(category, ''))) = ?",
            (canonical_label, raw_label),
        )


def seed_catalogue_feeds(conn: sqlite3.Connection) -> None:
    """Ensure the static catalogue exists in the service DB."""
    if not FEED_CATALOG:
        return

    for item in FEED_CATALOG:
        url = item.get("url") or ""
        name = (item.get("name") or url).strip()
        category = normalize_catalog_category(item.get("category"))
        subscribed = 1 if url in STARTER_CATALOG_URLS else 0
        if not url:
            continue
        try:
            conn.execute(
                """
                INSERT INTO feeds (url, title, subscribed, category)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(url) DO NOTHING
                """,
                (url, name or None, subscribed, category),
            )
        except Exception:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO feeds (url, title, subscribed) VALUES (?, ?, ?)",
                    (url, name or None, subscribed),
                )
            except Exception:
                pass
    normalize_catalog_categories_in_db(conn)
    conn.commit()


def seed_starter_subscriptions(conn: sqlite3.Connection) -> None:
    """Apply the starter bundle once for fresh installs and empty databases."""
    initialized = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (STARTER_FEEDS_INITIALIZED_KEY,),
    ).fetchone()
    if initialized:
        return

    subscribed_count = conn.execute(
        "SELECT COUNT(*) FROM feeds WHERE COALESCE(subscribed, 1) = 1"
    ).fetchone()[0]
    entry_count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    if subscribed_count == 0 and entry_count == 0 and STARTER_CATALOG_URLS:
        placeholders = ", ".join("?" for _ in STARTER_CATALOG_URLS)
        conn.execute(
            f"UPDATE feeds SET subscribed = 1 WHERE url IN ({placeholders})",
            tuple(sorted(STARTER_CATALOG_URLS)),
        )

    conn.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (STARTER_FEEDS_INITIALIZED_KEY, "true"),
    )
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
        normalize_catalog_categories_in_db(conn)
        conn.commit()
        rows = conn.execute(
            "SELECT url, name, category, description FROM user_catalog"
        ).fetchall()
    finally:
        conn.close()

    static_items = [
        {
            **item,
            "category": normalize_catalog_category(item.get("category")),
            "removable": False,
        }
        for item in FEED_CATALOG
    ]
    extras = [
        {
            "url": row["url"],
            "name": row["name"],
            "category": normalize_catalog_category(row["category"]),
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
