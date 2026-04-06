import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Optional

from fastapi import HTTPException

from myrssfeed.api.schemas import DetectRequest, SettingsUpdate
from myrssfeed.services import entries


class SystemAPIRoutes:
    def __init__(
        self,
        get_db: Callable[[], sqlite3.Connection],
        get_setting: Callable[[str], str],
        set_setting: Callable[[str, str], None],
        defaults: dict[str, str],
        reconfigure_scheduler: Callable[[], None],
        is_pipeline_running: Callable[[], bool],
        run_pipeline_async: Callable[[], bool],
        get_pipeline_progress: Callable[[], dict],
        is_newsletter_running: Callable[[], bool],
        run_newsletter_ingest_async: Callable[..., bool],
        logger,
        log_file: str,
    ) -> None:
        self.get_db = get_db
        self.get_setting = get_setting
        self.set_setting = set_setting
        self.defaults = defaults
        self.reconfigure_scheduler = reconfigure_scheduler
        self.is_pipeline_running = is_pipeline_running
        self.run_pipeline_async = run_pipeline_async
        self.get_pipeline_progress = get_pipeline_progress
        self.is_newsletter_running = is_newsletter_running
        self.run_newsletter_ingest_async = run_newsletter_ingest_async
        self.logger = logger
        self.log_file = log_file

    def register(self, app) -> None:
        app.get("/api/settings")(self.get_settings)
        app.post("/api/settings")(self.update_settings)
        app.post("/api/refresh", status_code=202)(self.trigger_refresh)
        app.get("/api/refresh/status")(self.get_refresh_status)
        app.get("/api/search")(self.live_search)
        app.post("/api/discover/detect")(self.detect_feeds)
        app.post("/api/newsletters/sync", status_code=202)(self.trigger_newsletter_sync)
        app.get("/api/newsletters/status")(self.get_newsletter_status)
        app.post("/api/wordrank", status_code=200)(self.run_wordrank_now)
        app.get("/api/wordrank/status")(self.get_wordrank_status)
        app.get("/api/logs")(self.get_logs)

    def get_settings(self):
        return {key: self.get_setting(key) for key in self.defaults}

    def update_settings(self, payload: SettingsUpdate):
        updates = payload.model_dump(exclude_none=True)
        for key, value in updates.items():
            self.set_setting(key, str(value))
        self.reconfigure_scheduler()
        return {key: self.get_setting(key) for key in self.defaults}

    def trigger_refresh(self):
        if self.is_pipeline_running():
            return {"status": "running", "message": "Pipeline already in progress."}
        started = self.run_pipeline_async()
        if not started:
            return {"status": "running", "message": "Pipeline already in progress."}
        return {"status": "started", "message": "Pipeline started in background."}

    def get_refresh_status(self, details: bool = False):
        running = self.is_pipeline_running()
        last_status = self.get_setting("pipeline_last_status") or "never"
        minutes_since_last_success = None
        ts = self.get_setting("pipeline_last_success_ts")
        if ts:
            try:
                last_dt = datetime.fromisoformat(ts)
                now = datetime.now(timezone.utc)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                diff = now - last_dt
                minutes_since_last_success = max(0, int(diff.total_seconds() // 60))
            except Exception:
                minutes_since_last_success = None
        progress = self.get_pipeline_progress()
        response = {
            "running": running,
            "last_status": last_status,
            "minutes_since_last_success": minutes_since_last_success,
            "stage": progress.get("stage"),
            "stage_label": progress.get("stage_label"),
            "message": progress.get("message"),
            "started_at": progress.get("started_at"),
            "updated_at": progress.get("updated_at"),
            "total_feeds": progress.get("total_feeds", 0),
            "completed_feeds": progress.get("completed_feeds", 0),
            "progress_percent": progress.get("progress_percent", 0),
            "current_feed": progress.get("current_feed"),
            "total_items_seen": progress.get("total_items_seen", 0),
            "total_new_entries": progress.get("total_new_entries", 0),
            "pruned_entries": progress.get("pruned_entries", 0),
            "quality_updates": progress.get("quality_updates", 0),
            "theme_updates": progress.get("theme_updates", 0),
        }
        if details:
            response["feed_results"] = progress.get("results", [])
        return response

    def live_search(
        self,
        q: Optional[str] = None,
        limit: int = 8,
        feed_id: Optional[int] = None,
        quality_level: Optional[int] = None,
        days: Optional[str] = None,
        scope: Optional[str] = None,
    ):
        if not q or not q.strip():
            return {"suggestions": [], "entries": []}

        query_text = q.strip()
        conn = self.get_db()
        try:
            days_int = entries.parse_days(days)
            source_scope = entries.normalize_source_scope(scope)
            active_feed_id = feed_id if source_scope == entries.SOURCE_SCOPE_MY else None
            filters, params = entries.build_entry_filters(
                query_text,
                active_feed_id,
                quality_level,
                days_int,
                source_scope,
                None,
            )
            query = """
                SELECT e.id, e.feed_id, f.title AS feed_title,
                       e.title, e.link, e.published,
                       e.assessment_label,
                       e.assessment_label_color
                FROM entries e
                JOIN feeds f ON f.id = e.feed_id
            """
            if filters:
                query += " WHERE " + " AND ".join(filters)
            query += " ORDER BY e.published DESC LIMIT ?"
            entry_rows = conn.execute(query, params + [limit]).fetchall()

            words_in_q = query_text.split()
            last_word = words_in_q[-1] if words_in_q else ""
            suggestions: list[str] = []
            if last_word and len(last_word) >= 2:
                suggestion_filters, suggestion_params = entries.build_entry_filters(
                    None,
                    active_feed_id,
                    quality_level,
                    days_int,
                    source_scope,
                    None,
                )
                title_query = """
                    SELECT e.title
                    FROM entries e
                    JOIN feeds f ON f.id = e.feed_id
                """
                title_filters = list(suggestion_filters)
                title_filters.append("e.title LIKE ?")
                title_query += " WHERE " + " AND ".join(title_filters)
                title_query += " LIMIT 200"
                title_rows = conn.execute(
                    title_query,
                    suggestion_params + [f"%{last_word}%"],
                ).fetchall()
                seen: set[str] = set()
                for row in title_rows:
                    for word in re.findall(r"[A-Za-z']+", row["title"]):
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
        finally:
            conn.close()
        return {"suggestions": suggestions, "entries": [dict(row) for row in entry_rows]}

    def detect_feeds(self, payload: DetectRequest):
        import socket

        raw_url = payload.url.strip()
        if not raw_url.startswith(("http://", "https://")):
            raw_url = "https://" + raw_url
        parsed = urllib.parse.urlparse(raw_url)
        if not parsed.netloc:
            raise HTTPException(status_code=422, detail="Invalid URL.")
        try:
            addr = socket.getaddrinfo(parsed.hostname, None)[0][4][0]
            if any(addr.startswith(prefix) for prefix in ("127.", "10.", "192.168.", "169.254.", "::1")):
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
                attr_map = dict(attrs)
                feed_type = attr_map.get("type", "").lower()
                if feed_type in ("application/rss+xml", "application/atom+xml", "application/rdf+xml"):
                    href = attr_map.get("href", "")
                    if href:
                        self.feeds.append({"name": attr_map.get("title", ""), "url": href})

        headers = {"User-Agent": "myRSSfeed/1.0 (RSS discovery)"}
        request = urllib.request.Request(raw_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read(512 * 1024).decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=422, detail=f"Could not reach URL: {exc.reason}")
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Request failed: {exc}")

        if any(token in content_type for token in ("rss", "atom", "xml")):
            title = ""
            match = re.search(r"<title[^>]*>([^<]{1,120})</title>", body, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
            return {"feeds": [{"name": title or "Feed", "url": raw_url}]}

        parser = LinkParser()
        parser.feed(body)
        feeds = []
        seen = set()
        for feed in parser.feeds:
            url = urllib.parse.urljoin(raw_url, feed["url"])
            if url not in seen:
                seen.add(url)
                feeds.append({"name": feed["name"], "url": url})

        if not feeds:
            base = f"{parsed.scheme}://{parsed.netloc}"
            for path in ["/rss", "/feed", "/rss.xml", "/atom.xml", "/feed.xml", "/blog/feed", "/blog/rss"]:
                probe_url = base + path
                try:
                    probe_request = urllib.request.Request(probe_url, headers=headers, method="HEAD")
                    with urllib.request.urlopen(probe_request, timeout=4) as response:
                        content_type = response.headers.get("Content-Type", "")
                        if any(token in content_type for token in ("rss", "atom", "xml")) and probe_url not in seen:
                            seen.add(probe_url)
                            feeds.append({"name": "", "url": probe_url})
                except Exception:
                    continue

        return {"feeds": feeds[:8]}

    def trigger_newsletter_sync(self):
        started = self.run_newsletter_ingest_async(require_enabled=True)
        if not started:
            return {"status": "running", "message": "Newsletter sync already in progress."}
        return {"status": "started", "message": "Newsletter sync started in background."}

    def get_newsletter_status(self):
        running = self.is_newsletter_running()
        newsletter_enabled = (self.get_setting("newsletter_enabled") or "false").lower() == "true"
        last_status = self.get_setting("newsletter_last_status") or "never"
        if not newsletter_enabled and not running:
            last_status = "disabled"
        return {
            "running": running,
            "last_status": last_status,
            "minutes_since_last_success": entries.minutes_since_iso_timestamp(
                self.get_setting("newsletter_last_success_ts")
            ),
            "last_error": self.get_setting("newsletter_last_error") or "",
        }

    def run_wordrank_now(self):
        from myrssfeed.scripts.wordrank import run_wordrank

        run_wordrank()
        final_status = self.get_setting("wordrank_last_status") or "never"
        if final_status == "success":
            return {"status": "success", "message": "WordRank completed."}
        return {"status": "error", "message": "WordRank failed."}

    def get_wordrank_status(self):
        last_status = self.get_setting("wordrank_last_status") or "never"
        running = last_status == "running"
        return {
            "running": running,
            "last_status": last_status,
            "minutes_since_last_success": entries.minutes_since_iso_timestamp(
                self.get_setting("wordrank_last_success_ts")
            ),
        }

    def get_logs(self, lines: int = 100):
        if not os.path.exists(self.log_file):
            return {"lines": []}
        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as log_handle:
                all_lines = log_handle.readlines()
            return {"lines": [line.rstrip("\n") for line in all_lines[-lines:]]}
        except Exception as exc:
            self.logger.warning("Could not read log file: %s", exc)
            return {"lines": []}
