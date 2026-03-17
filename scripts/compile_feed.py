import sys
import os
import re
import logging
import socket
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Optional, Tuple

import feedparser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.helpers import get_db, get_setting  # noqa: E402

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


def _is_private_ip(hostname: str) -> bool:
    """Best-effort guard against fetching internal addresses."""
    try:
        addr = socket.getaddrinfo(hostname, None)[0][4][0]
    except Exception:
        return False
    private_prefixes = ("127.", "10.", "192.168.", "169.254.", "::1")
    return any(addr.startswith(p) for p in private_prefixes)


class _MetaParser(HTMLParser):
    """Lightweight extractor for basic OpenGraph/Twitter metadata."""

    def __init__(self) -> None:
        super().__init__()
        self.title: Optional[str] = None
        self.og_title: Optional[str] = None
        self.og_description: Optional[str] = None
        self.og_image: Optional[str] = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l == "title":
            self._in_title = True
            return
        if tag_l != "meta":
            return
        d = {k.lower(): v for k, v in attrs}
        prop = d.get("property", "").lower()
        name = d.get("name", "").lower()
        content = d.get("content", "")
        if not content:
            return
        if prop == "og:title" or name == "twitter:title":
            if not self.og_title:
                self.og_title = content.strip()
        elif prop == "og:description" or name == "twitter:description":
            if not self.og_description:
                self.og_description = content.strip()
        elif prop == "og:image" or name == "twitter:image":
            if not self.og_image:
                self.og_image = content.strip()

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            text = data.strip()
            if text:
                # Take the first non-empty <title>
                if not self.title:
                    self.title = text


def _scrape_url(link: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Fetch a URL and return (og_title, og_description, og_image_url, full_content_text).

    This is deliberately conservative: short timeout, size cap, internal-IP guard.
    """
    if not link:
        return None, None, None, None

    try:
        parsed = urllib.parse.urlparse(link)
    except Exception:
        return None, None, None, None

    if not parsed.scheme or not parsed.netloc:
        return None, None, None, None

    if _is_private_ip(parsed.hostname or ""):
        logger.info("Scraper: skipping private address %s", link)
        return None, None, None, None

    try:
        timeout_s = float(get_setting("scrape_timeout_seconds") or "6")
    except (TypeError, ValueError):
        timeout_s = 6.0

    try:
        max_bytes = int(get_setting("scrape_max_bytes") or str(512 * 1024))
    except (TypeError, ValueError):
        max_bytes = 512 * 1024

    headers = {"User-Agent": "myRSSfeed/1.0 (content enrichment)"}
    req = urllib.request.Request(link, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return None, None, None, None
            raw = resp.read(max_bytes)
    except urllib.error.URLError as exc:
        logger.info("Scraper: URL error for %s: %s", link, exc)
        return None, None, None, None
    except Exception as exc:
        logger.info("Scraper: failed for %s: %s", link, exc)
        return None, None, None, None

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return None, None, None, None

    parser = _MetaParser()
    try:
        parser.feed(text)
    except Exception:
        # Parsing failures are non-fatal; just use what we have so far.
        pass

    og_title = parser.og_title or parser.title
    og_description = parser.og_description
    og_image = parser.og_image

    # Resolve image URL against page URL if relative
    if og_image:
        og_image = urllib.parse.urljoin(link, og_image)

    full_content = None  # Placeholder for future readability-style extraction

    return og_title, og_description, og_image, full_content


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
                og_title, og_description, og_image_url, full_content = _scrape_url(link)
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
