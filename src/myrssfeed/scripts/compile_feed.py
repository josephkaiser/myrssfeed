import sys
import os
import re
import logging
import calendar
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser

from myrssfeed.utils.helpers import get_db, get_setting

logger = logging.getLogger(__name__)

# Max lengths for DB/text fields to avoid bloat and encoding issues on Pi
TITLE_MAX_LEN = 2000
SUMMARY_MAX_LEN = 50_000
LINK_MAX_LEN = 2048


def _extract_thumbnail(entry) -> Optional[str]:
    for media in getattr(entry, "media_content", []):
        url = media.get("url", "")
        mime = media.get("type", "")
        if mime.startswith("image/") or url.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return url
    for thumb in getattr(entry, "media_thumbnail", []):
        if thumb.get("url"):
            return thumb["url"]
    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("image/"):
            return enc.get("href")
    summary = getattr(entry, "summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _normalize_link(link: Optional[str]) -> Optional[str]:
    """Strip and optionally normalize link for storage/dedup. Returns None if empty."""
    if link is None:
        return None
    s = (link or "").strip()
    if not s:
        return None
    # Optional: strip fragment so same article with #section dedupes (max one per feed)
    if "#" in s:
        s = s.split("#", 1)[0].rstrip("/") or s
    if len(s) > LINK_MAX_LEN:
        s = s[:LINK_MAX_LEN]
    return s


def _normalize_text(text: Optional[str], max_len: int = TITLE_MAX_LEN) -> str:
    """Return stripped, truncated string; None/empty -> empty string."""
    if text is None:
        return ""
    out = (text or "").strip()
    if len(out) > max_len:
        out = out[:max_len]
    return out


def _parse_date(raw: Optional[str], parsed_9tuple=None) -> str:
    """Normalize date to ISO-8601 UTC string. Prefers feedparser published_parsed when given (UTC)."""
    if parsed_9tuple is not None:
        try:
            ts = calendar.timegm(parsed_9tuple)  # struct_time is UTC in feedparser
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except Exception:
        return raw if isinstance(raw, str) else datetime.now(timezone.utc).isoformat()


def _process_entry(
    cursor,
    feed_id: int,
    entry,
    source_uid: Optional[str],
    new_count_ref: list,
) -> bool:
    """Parse, normalize, and insert one entry. Mutates *_ref counters."""
    link = _normalize_link(getattr(entry, "link", None))
    source_uid = _normalize_text(source_uid or link or "", LINK_MAX_LEN)
    if not source_uid:
        return False
    title = _normalize_text(getattr(entry, "title", "") or "(no title)", TITLE_MAX_LEN)
    summary = _normalize_text(getattr(entry, "summary", ""), SUMMARY_MAX_LEN)
    published = _parse_date(
        getattr(entry, "published", None),
        getattr(entry, "published_parsed", None),
    )
    thumbnail_url = _extract_thumbnail(entry)
    if thumbnail_url and len(thumbnail_url) > LINK_MAX_LEN:
        thumbnail_url = thumbnail_url[:LINK_MAX_LEN]

    og_title = getattr(entry, "og_title", None)
    og_description = getattr(entry, "og_description", None)
    og_image_url = getattr(entry, "og_image_url", None)
    full_content = getattr(entry, "full_content", None)

    try:
        cursor.execute(
            """
            INSERT INTO entries (
                feed_id, source_uid, title, link, published, summary, thumbnail_url,
                og_title, og_description, og_image_url, full_content
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feed_id,
                source_uid,
                title,
                link,
                published,
                summary,
                thumbnail_url,
                og_title,
                og_description,
                og_image_url,
                full_content,
            ),
        )
        new_count_ref[0] += 1
        return True
    except Exception:
        # UNIQUE(feed_id, source_uid) — entry already stored
        return False


def run_compile_feed():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, url, title FROM feeds WHERE COALESCE(kind, 'rss') = 'rss'")
    feeds = cursor.fetchall()

    if not feeds:
        logger.info("No feeds configured — nothing to fetch.")
        conn.close()
        return

    new_count_ref = [0]

    for row in feeds:
        feed_id, url, feed_title = row["id"], row["url"], row["title"]
        logger.info("Fetching %s", url)
        try:
            d = feedparser.parse(url, agent="myRSSfeed/1.0")
        except Exception as exc:
            logger.warning("Failed to fetch/parse feed %s: %s", url, exc)
            continue

        if getattr(d, "bozo", False) and getattr(d, "bozo_exception", None):
            logger.warning(
                "Feed had parse issues (bozo) %s: %s — continuing with entries.",
                url,
                d.bozo_exception,
            )

        # Backfill feed title if not set
        if not feed_title and d.feed.get("title"):
            try:
                cursor.execute(
                    "UPDATE feeds SET title = ? WHERE id = ?",
                    (d.feed.title, feed_id),
                )
            except Exception as exc:
                logger.debug("Could not backfill feed title: %s", exc)

        for entry in d.entries:
            try:
                _process_entry(
                    cursor=cursor,
                    feed_id=feed_id,
                    entry=entry,
                    source_uid=getattr(entry, "link", None),
                    new_count_ref=new_count_ref,
                )
            except Exception as exc:
                logger.debug("Skipping malformed entry in feed %s: %s", url, exc)
                continue

    new_count = new_count_ref[0]
    conn.commit()
    conn.close()
    logger.info(
        "Compile complete. %d new entries stored.",
        new_count,
    )

    _prune_old_entries()


def _prune_old_entries() -> None:
    """Remove entries older than retention_days. Never raises; logs on failure."""
    try:
        days = int(get_setting("retention_days"))
    except (ValueError, TypeError):
        days = 90

    if days <= 0:
        logger.info("Pruning disabled (retention_days=%d).", days)
        return

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = get_db()
        cursor = conn.execute(
            "DELETE FROM entries WHERE published < ?",
            (cutoff,),
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted:
            logger.info("Pruned %d entr%s older than %d days.", deleted, "y" if deleted == 1 else "ies", days)
    except Exception as exc:
        logger.warning("Prune failed (retention_days=%d): %s", days, exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_compile_feed()
