import logging
import time
from datetime import datetime, timezone
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Optional, Tuple

# One retry for transient failures (timeout, connection reset) — keeps Pi friendly
SCRAPE_RETRY_DELAY_SEC = 2
SCRAPE_MAX_ATTEMPTS = 2

from utils.helpers import get_db, get_setting, set_setting


logger = logging.getLogger(__name__)

_scraper_lock = threading.Lock()
_scraper_running = False


def is_scraper_running() -> bool:
    return _scraper_running


def _record_scrape_status(status: str) -> None:
    """
    Best-effort helper to persist the last manual scrape/enrich status.

    Status values are simple strings ("running" | "success" | "error").
    """
    try:
        set_setting("scrape_last_status", status)
        if status == "success":
            # Record timestamp of last successful run for age display.
            set_setting("scrape_last_success_ts", datetime.now(timezone.utc).isoformat())
    except Exception:
        logger.exception("Could not record scrape status %r", status)


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
            if text and not self.title:
                # Take the first non-empty <title>
                self.title = text


def scrape_url(link: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Fetch a URL and return (og_title, og_description, og_image_url, full_content_text)."""
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
    raw = None
    for attempt in range(SCRAPE_MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    return None, None, None, None
                raw = resp.read(max_bytes)
            break
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if attempt < SCRAPE_MAX_ATTEMPTS - 1:
                logger.debug("Scraper: attempt %s failed for %s: %s; retrying.", attempt + 1, link, exc)
                time.sleep(SCRAPE_RETRY_DELAY_SEC)
            else:
                logger.info("Scraper: URL error for %s: %s", link, exc)
                return None, None, None, None
        except Exception as exc:
            logger.info("Scraper: failed for %s: %s", link, exc)
            return None, None, None, None
    if raw is None:
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


def run_scraper_for_all_entries() -> None:
    """Scrape/enrich entries that are missing OpenGraph metadata."""
    conn = get_db()
    cursor = conn.cursor()

    try:
        scrape_enabled = (get_setting("scrape_enabled") or "true").lower() == "true"
    except Exception:
        scrape_enabled = True

    if not scrape_enabled:
        logger.info("Manual scraper disabled via settings (scrape_enabled=false).")
        conn.close()
        return

    try:
        scrape_budget = int(get_setting("scrape_max_per_run") or "40")
    except (TypeError, ValueError):
        scrape_budget = 40

    scraped_count = 0

    rows = cursor.execute(
        """
        SELECT id, link
        FROM entries
        WHERE link IS NOT NULL
          AND (og_title IS NULL OR og_description IS NULL OR og_image_url IS NULL OR full_content IS NULL)
        ORDER BY id DESC
        """
    ).fetchall()

    had_error = False

    for row in rows:
        if scrape_budget <= 0:
            break
        entry_id = row["id"]
        link = row["link"]
        if not link:
            continue
        try:
            og_title, og_description, og_image_url, full_content = scrape_url(link)
        except Exception:
            had_error = True
            logger.exception("Scraper: unexpected failure for %s", link)
            continue

        if not any([og_title, og_description, og_image_url, full_content]):
            continue

        cursor.execute(
            """
            UPDATE entries
            SET og_title = COALESCE(og_title, ?),
                og_description = COALESCE(og_description, ?),
                og_image_url = COALESCE(og_image_url, ?),
                full_content = COALESCE(full_content, ?)
            WHERE id = ?
            """,
            (og_title, og_description, og_image_url, full_content, entry_id),
        )
        scraped_count += 1
        scrape_budget -= 1

    conn.commit()
    conn.close()
    final_status = "error" if had_error else "success"
    _record_scrape_status(final_status)
    logger.info("Manual scraper complete with status %s. %d entries enriched.", final_status, scraped_count)


def run_scraper():
    """Run the scraper in the foreground with locking."""
    global _scraper_running
    if not _scraper_lock.acquire(blocking=False):
        logger.info("Scraper already running — skipping concurrent start.")
        return
    _scraper_running = True
    _record_scrape_status("running")
    try:
        run_scraper_for_all_entries()
    finally:
        _scraper_running = False
        _scraper_lock.release()


def run_scraper_async() -> bool:
    """Start the scraper in a daemon thread.

    Returns True if started, False if already running.
    """
    if _scraper_running:
        return False
    t = threading.Thread(target=run_scraper, daemon=True, name="scraper")
    t.start()
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_scraper()

