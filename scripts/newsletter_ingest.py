import hashlib
import imaplib
import logging
import os
import re
import sys
import threading
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import Message
from html import escape
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.helpers import get_db, get_setting, set_setting  # noqa: E402
from scripts.compile_feed import _normalize_text, _parse_date, _process_entry  # noqa: E402

logger = logging.getLogger(__name__)

_newsletter_lock = threading.Lock()
_newsletter_running = False

NEWSLETTER_FEED_URL = "newsletter://inbox"
NEWSLETTER_FEED_TITLE = "Newsletters"


def is_newsletter_running() -> bool:
    return _newsletter_running


def _record_newsletter_status(status: str, error: str = "") -> None:
    try:
        set_setting("newsletter_last_status", status)
        set_setting("newsletter_last_error", error or "")
        if status == "success":
            set_setting("newsletter_last_success_ts", datetime.now(timezone.utc).isoformat())
    except Exception:
        logger.exception("Could not record newsletter status %r", status)


def _decode_header_value(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        return str(raw).strip()


def _safe_int(value: str, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _newsletter_config() -> dict:
    return {
        "host": (get_setting("newsletter_imap_host") or "").strip(),
        "port": _safe_int(get_setting("newsletter_imap_port") or "993", 993),
        "username": (get_setting("newsletter_imap_username") or "").strip(),
        "password": get_setting("newsletter_imap_password") or "",
        "folder": (get_setting("newsletter_imap_folder") or "INBOX").strip() or "INBOX",
    }


def _ensure_newsletter_feed(conn) -> int:
    row = conn.execute(
        "SELECT id FROM feeds WHERE COALESCE(kind, 'rss') = 'newsletter' LIMIT 1"
    ).fetchone()
    if row:
        return int(row["id"])

    cursor = conn.execute(
        """
        INSERT INTO feeds (url, title, subscribed, kind)
        VALUES (?, ?, 0, 'newsletter')
        """,
        (NEWSLETTER_FEED_URL, NEWSLETTER_FEED_TITLE),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class _HtmlEmailExtractor(HTMLParser):
    BLOCK_TAGS = {
        "article",
        "div",
        "footer",
        "header",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "table",
        "tr",
        "ul",
        "ol",
        "blockquote",
    }
    SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._in_anchor = False
        self._anchor_href: Optional[str] = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag_l == "br":
            self.text_parts.append("\n")
        elif tag_l in self.BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag_l == "a":
            self._in_anchor = True
            self._anchor_href = dict(attrs).get("href", "").strip()
            self._anchor_text = []

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        if tag_l in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag_l == "a":
            href = (self._anchor_href or "").strip()
            text = " ".join(self._anchor_text).strip()
            if href:
                self.links.append((href, text))
            self._in_anchor = False
            self._anchor_href = None
            self._anchor_text = []
        elif tag_l in self.BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        self.text_parts.append(text)
        if self._in_anchor:
            self._anchor_text.append(text)

    def text(self) -> str:
        raw = " ".join(self.text_parts)
        return _normalize_whitespace(raw)


def _extract_message_text_and_links(html_body: str) -> tuple[str, list[tuple[str, str]]]:
    parser = _HtmlEmailExtractor()
    try:
        parser.feed(html_body)
    except Exception:
        logger.debug("Newsletter HTML parsing failed; falling back to raw text.", exc_info=True)
    return parser.text(), parser.links


def _select_canonical_link(plain_text: str, links: list[tuple[str, str]]) -> Optional[str]:
    candidates = (
        "view online",
        "read online",
        "open in browser",
        "view this email",
        "browser version",
        "online version",
    )
    for href, text in links:
        link_text = (text or "").lower()
        if href.startswith(("http://", "https://")) and any(token in link_text for token in candidates):
            return href
    for href, _ in links:
        if href.startswith(("http://", "https://")):
            return href
    m = re.search(r"https?://[^\s<>\"]+", plain_text or "")
    return m.group(0) if m else None


def _extract_message_body(msg: Message) -> tuple[str, Optional[str]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment":
            continue
        content_type = (part.get_content_type() or "").lower()
        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace")

        if not isinstance(content, str):
            content = str(content)

        if content_type == "text/plain":
            plain_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(content)

    plain_text = _normalize_whitespace("\n\n".join(plain_parts)) if plain_parts else ""
    if html_parts:
        html_text, links = _extract_message_text_and_links("\n\n".join(html_parts))
        if html_text:
            plain_text = html_text
        elif not plain_text:
            plain_text = html_text
        canonical = _select_canonical_link(plain_text, links)
    else:
        canonical = _select_canonical_link(plain_text, [])

    return plain_text, canonical


def _truncate_plain_text(text: str, limit: int = 1800) -> str:
    clean = _normalize_whitespace(text)
    if len(clean) <= limit:
        return clean
    cut = clean[:limit].rsplit(" ", 1)[0].strip()
    return f"{cut}..."


def _plain_text_to_safe_html(text: str) -> str:
    clean = _normalize_whitespace(text)
    if not clean:
        return ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", clean) if block.strip()]
    if not blocks:
        blocks = [clean]
    return "\n".join(
        f"<p>{escape(block).replace(chr(10), '<br />')}</p>"
        for block in blocks
    )


def _message_source_uid(msg: Message, subject: str, sender: str, body: str) -> str:
    message_id = (msg.get("Message-ID") or "").strip().strip("<>")
    if message_id:
        return message_id
    payload = "|".join([
        subject,
        sender,
        (msg.get("Date") or "").strip(),
        body[:4000],
    ])
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _build_entry_like(msg: Message) -> tuple[SimpleNamespace, str]:
    subject = _decode_header_value(msg.get("Subject")) or "(no subject)"
    sender = _decode_header_value(msg.get("From"))
    if sender:
        title = subject
    else:
        title = subject or "Newsletter"

    plain_text, canonical_link = _extract_message_body(msg)
    summary_text = _truncate_plain_text(plain_text)
    full_content = _plain_text_to_safe_html(plain_text)
    summary_html = _plain_text_to_safe_html(summary_text or plain_text)

    published = _parse_date(msg.get("Date"))
    source_uid = _message_source_uid(msg, title, sender, plain_text)

    entry = SimpleNamespace(
        title=title,
        link=canonical_link,
        summary=summary_html,
        published=published,
        published_parsed=None,
        media_content=[],
        media_thumbnail=[],
        enclosures=[],
    )
    return entry, source_uid, full_content


def _connect_imap() -> imaplib.IMAP4:
    cfg = _newsletter_config()
    host = str(cfg["host"]).strip()
    if not host:
        raise RuntimeError("IMAP host is not configured.")

    port = int(cfg["port"])
    logger.info("Connecting to newsletter IMAP host %s:%d", host, port)
    return imaplib.IMAP4_SSL(host, port)


def _process_message(cursor, feed_id: int, msg: Message) -> bool:
    entry, source_uid, full_content = _build_entry_like(msg)
    # Reuse the RSS insert path so newsletters land in the same schema.
    entry.full_content = full_content
    return bool(
        _process_entry(
            cursor=cursor,
            feed_id=feed_id,
            entry=entry,
            source_uid=source_uid,
            scrape_enabled=False,
            scrape_budget_ref=[0],
            new_count_ref=[0],
            scraped_count_ref=[0],
        )
    )


def run_newsletter_ingest(require_enabled: bool = True) -> None:
    global _newsletter_running
    if not _newsletter_lock.acquire(blocking=False):
        logger.info("Newsletter ingest already running — skipping concurrent start.")
        return
    _newsletter_running = True
    _record_newsletter_status("running")

    conn = None
    client = None
    try:
        enabled = (get_setting("newsletter_enabled") or "false").lower() == "true"
        if require_enabled and not enabled:
            logger.info("Newsletter polling disabled via settings.")
            _record_newsletter_status("disabled")
            return

        cfg = _newsletter_config()
        client = _connect_imap()
        if cfg["username"]:
            client.login(str(cfg["username"]), str(cfg["password"]))

        folder = str(cfg["folder"]) or "INBOX"
        client.select(folder)

        status, data = client.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("IMAP search for unseen messages failed.")

        ids = []
        for chunk in data or []:
            if not chunk:
                continue
            ids.extend(part for part in chunk.decode("utf-8", errors="ignore").split() if part)

        conn = get_db()
        cursor = conn.cursor()
        feed_id = _ensure_newsletter_feed(conn)

        new_count = 0

        for msg_id in ids:
            status, fetched = client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetched:
                logger.debug("Newsletter fetch failed for message %s", msg_id)
                continue
            raw_message = None
            for item in fetched:
                if isinstance(item, tuple) and len(item) >= 2:
                    raw_message = item[1]
                    break
            if not raw_message:
                continue

            msg = message_from_bytes(raw_message, policy=policy.default)
            if _process_message(cursor, feed_id, msg):
                new_count += 1

        conn.commit()
        _record_newsletter_status("success")
        logger.info("Newsletter ingest complete. %d new entries stored.", new_count)
    except Exception as exc:
        logger.exception("Newsletter ingest failed: %s", exc)
        _record_newsletter_status("error", str(exc))
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        try:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
                try:
                    client.logout()
                except Exception:
                    pass
        finally:
            _newsletter_running = False
            _newsletter_lock.release()


def run_newsletter_ingest_async(require_enabled: bool = True) -> bool:
    if _newsletter_running:
        return False
    thread = threading.Thread(
        target=run_newsletter_ingest,
        kwargs={"require_enabled": require_enabled},
        daemon=True,
        name="newsletter-ingest",
    )
    thread.start()
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_newsletter_ingest()
