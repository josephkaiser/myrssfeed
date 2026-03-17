import sys
import os
import re
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Optional, Tuple

import feedparser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.helpers import get_db, get_setting  # noqa: E402
from scripts.scraper import scrape_url  # noqa: E402

logger = logging.getLogger(__name__)


def _extract_thumbnail(entry) -> str | None:
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


def _parse_date(raw: str) -> str:
    """Normalize any RFC 2822 / ISO date string to an ISO-8601 UTC string."""
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except Exception:
        return raw


def run_compile_feed():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, url, title FROM feeds")
    feeds = cursor.fetchall()

    if not feeds:
        logger.info("No feeds configured — nothing to fetch.")
        conn.close()
        return

    try:
        scrape_enabled = (get_setting("scrape_enabled") or "true").lower() == "true"
    except Exception:
        scrape_enabled = True

    try:
        scrape_budget = int(get_setting("scrape_max_per_run") or "40")
    except (TypeError, ValueError):
        scrape_budget = 40

    new_count = 0
    scraped_count = 0

    for row in feeds:
        feed_id, url, feed_title = row["id"], row["url"], row["title"]
        logger.info("Fetching %s", url)
        try:
            d = feedparser.parse(url, agent="myRSSfeed/1.0")
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", url, exc)
            continue

        # Backfill feed title if not set
        if not feed_title and d.feed.get("title"):
            cursor.execute(
                "UPDATE feeds SET title = ? WHERE id = ?",
                (d.feed.title, feed_id),
            )

        for entry in d.entries:
            title = getattr(entry, "title", "(no title)")
            link = getattr(entry, "link", "")
            published = _parse_date(getattr(entry, "published", ""))
            summary = getattr(entry, "summary", "")
            thumbnail_url = _extract_thumbnail(entry)

            og_title = None
            og_description = None
            og_image_url = None
            full_content = None

            should_scrape = scrape_enabled and scrape_budget > 0 and bool(link)

            if should_scrape:
                og_title, og_description, og_image_url, full_content = scrape_url(link)
                if any([og_title, og_description, og_image_url, full_content]):
                    scraped_count += 1
                    scrape_budget -= 1

            try:
                cursor.execute(
                    """
                    INSERT INTO entries (
                        feed_id, title, link, published, summary, thumbnail_url,
                        og_title, og_description, og_image_url, full_content
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feed_id,
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
                new_count += 1
            except Exception:
                # UNIQUE constraint — entry already stored
                pass

    conn.commit()
    conn.close()
    logger.info(
        "Compile complete. %d new entries stored. %d pages scraped for enrichment.",
        new_count,
        scraped_count,
    )

    _prune_old_entries()


def _prune_old_entries():
    try:
        days = int(get_setting("retention_days"))
    except (ValueError, TypeError):
        days = 90

    if days <= 0:
        logger.info("Pruning disabled (retention_days=%d).", days)
        return

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_compile_feed()
