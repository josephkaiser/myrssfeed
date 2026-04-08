import json
import logging
import sqlite3
from typing import Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from myrssfeed.scripts.scheduler import get_pipeline_schedule_settings
from myrssfeed.services import catalog, entries
from myrssfeed.services.subscriptions import apply_effective_subscription, filter_subscribed_rows


class UIRoutes:
    def __init__(
        self,
        templates,
        get_db: Callable[[], sqlite3.Connection],
        get_setting: Callable[[str], str],
        set_setting: Callable[[str, str], None],
        defaults: dict[str, str],
        logger: logging.Logger,
    ) -> None:
        self.templates = templates
        self.get_db = get_db
        self.get_setting = get_setting
        self.set_setting = set_setting
        self.defaults = defaults
        self.logger = logger

    def register(self, app) -> None:
        app.get("/", response_class=HTMLResponse)(self.index)
        app.get("/article/{entry_id}", response_class=HTMLResponse)(self.article_page)
        app.get("/feeds", response_class=HTMLResponse)(self.feeds_page)
        app.get("/add-feed", response_class=HTMLResponse)(self.add_feed_page)
        app.get("/discover", response_class=HTMLResponse)(self.discover_page)
        app.get("/settings", response_class=HTMLResponse)(self.settings_page)
        app.get("/stats", response_class=HTMLResponse)(self.stats_page)

    def _load_subscribed_feeds(self, conn: sqlite3.Connection, order_by: str = "title") -> list[dict]:
        rows = conn.execute(
            f"""
            SELECT id, url, title, color, COALESCE(subscribed, 1) AS subscribed
            FROM feeds
            ORDER BY {order_by}
            """
        ).fetchall()
        return filter_subscribed_rows([dict(row) for row in rows])

    def index(
        self,
        request: Request,
        q: Optional[str] = None,
        feed_id: Optional[int] = None,
        quality_level: Optional[int] = None,
        days: Optional[str] = None,
        scope: Optional[str] = None,
        themes: Optional[str] = None,
        read_status: Optional[str] = None,
        sort: Optional[str] = None,
    ):
        days_int = entries.parse_days(days)
        source_scope = entries.normalize_source_scope(scope)
        theme_labels = entries.parse_themes_param(themes)
        read_status_val = entries.normalize_read_status(read_status)
        read_status_param = read_status_val if read_status_val != entries.READ_STATUS_UNREAD else None
        sort_val = entries.normalize_sort(sort)
        active_feed_id = feed_id if source_scope == entries.SOURCE_SCOPE_MY else None

        conn = self.get_db()
        feeds = self._load_subscribed_feeds(conn)
        feed_map = catalog.build_feed_map(feeds)

        filters, params = entries.build_entry_filters(
            q,
            active_feed_id,
            quality_level,
            days_int,
            source_scope,
            theme_labels,
            read_status_val,
        )
        count_query = "SELECT COUNT(*) FROM entries e JOIN feeds f ON f.id = e.feed_id"
        if filters:
            count_query += " WHERE " + " AND ".join(filters)
        total_entries = conn.execute(count_query, params).fetchone()[0]
        random_seed = entries.random_seed_from_request(request)

        try:
            max_entries = int(self.get_setting("max_entries") or "1000")
        except (ValueError, TypeError):
            max_entries = 1000
        if max_entries <= 0:
            max_entries = 1000

        initial_limit = min(max_entries, 40)
        theme_param = ",".join(sorted(theme_labels)) if theme_labels is not None else None
        entries_list = entries.fetch_ranked_entries(
            conn,
            random_seed,
            q,
            active_feed_id,
            quality_level,
            days_int,
            source_scope,
            theme_labels,
            read_status_val,
            sort_val,
        )[:initial_limit]
        trending = entries.load_trending(conn, source_scope=source_scope)
        conn.close()

        return self.templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "feeds": feeds,
                "feed_map": feed_map,
                "entries": entries_list,
                "total_entries": total_entries,
                "total_entries_display": f"{total_entries:,}",
                "trending": trending,
                "q": q or "",
                "active_feed_id": active_feed_id,
                "date_range": days_int if (days_int is not None and days_int in entries.DATE_RANGE_DAYS) else None,
                "quality_level": quality_level,
                "source_scope": source_scope,
                "read_status": read_status_val,
                "show_read": read_status_val != entries.READ_STATUS_UNREAD,
                "sort": sort_val,
                "my_feed_url": entries.build_url_with_query_params(
                    "/",
                    {
                        "q": q or None,
                        "feed_id": str(active_feed_id) if active_feed_id is not None else None,
                        "quality_level": str(quality_level) if quality_level is not None else None,
                        "days": str(days_int) if days_int is not None else None,
                        "scope": entries.SOURCE_SCOPE_MY,
                        "themes": theme_param,
                        "read_status": read_status_param,
                        "sort": sort_val if sort_val != entries.SORT_CHRONOLOGICAL else None,
                    },
                ),
                "discover_feed_url": entries.build_url_with_query_params(
                    "/",
                    {
                        "q": q or None,
                        "quality_level": str(quality_level) if quality_level is not None else None,
                        "days": str(days_int) if days_int is not None else None,
                        "scope": entries.SOURCE_SCOPE_DISCOVER,
                        "themes": theme_param,
                        "read_status": read_status_param,
                        "sort": sort_val if sort_val != entries.SORT_CHRONOLOGICAL else None,
                    },
                ),
                "clear_url": entries.build_url_with_query_params(
                    "/",
                    {
                        "feed_id": str(active_feed_id) if active_feed_id is not None else None,
                        "quality_level": str(quality_level) if quality_level is not None else None,
                        "scope": source_scope,
                        "themes": theme_param,
                        "read_status": read_status_param,
                        "sort": sort_val if sort_val != entries.SORT_CHRONOLOGICAL else None,
                    },
                ),
            },
        )

    def article_page(self, request: Request, entry_id: int):
        conn = self.get_db()
        row = conn.execute(
            """
            SELECT e.id, e.feed_id, f.title AS feed_title,
                   e.title, e.link, e.published, e.summary,
                   e.thumbnail_url,
                   e.og_title, e.og_description, e.og_image_url, e.full_content,
                   COALESCE(e.read, 0) AS read,
                   e.assessment_label,
                   e.assessment_label_color
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
        if not entry.get("read"):
            conn.execute("UPDATE entries SET read = 1 WHERE id = ?", (entry_id,))
            conn.commit()
            entry["read"] = 1
        q = request.query_params.get("q")
        feed_id = entries.parse_int(request.query_params.get("feed_id"))
        quality_level = entries.parse_int(request.query_params.get("quality_level"))
        days_int = entries.parse_days(request.query_params.get("days"))
        source_scope = entries.normalize_source_scope(request.query_params.get("scope"))
        theme_labels = entries.parse_themes_param(request.query_params.get("themes"))
        read_status_val = entries.normalize_read_status(request.query_params.get("read_status"))
        read_status_param = read_status_val if read_status_val != entries.READ_STATUS_UNREAD else None
        sort_val = entries.normalize_sort(request.query_params.get("sort"))
        active_feed_id = feed_id if source_scope == entries.SOURCE_SCOPE_MY else None
        back_url = entries.build_url_with_query_params(
            "/",
            {
                "q": request.query_params.get("q"),
                "feed_id": request.query_params.get("feed_id"),
                "quality_level": request.query_params.get("quality_level"),
                "days": request.query_params.get("days"),
                "scope": request.query_params.get("scope"),
                "themes": ",".join(sorted(theme_labels)) if theme_labels is not None else None,
                "read_status": read_status_param,
                "sort": sort_val if sort_val != entries.SORT_CHRONOLOGICAL else None,
            },
        )
        feed_row = conn.execute(
            "SELECT id, url, title, color FROM feeds WHERE id = ?",
            (entry["feed_id"],),
        ).fetchone()
        conn.close()

        if feed_row:
            feed_map = catalog.build_feed_map([dict(feed_row)])
        else:
            feed_map = {
                entry["feed_id"]: {
                    "title": entry["feed_title"],
                    "domain": "",
                    "color": None,
                }
            }
        return self.templates.TemplateResponse(
            request=request,
            name="article.html",
            context={
                "request": request,
                "entry": entry,
                "feed_map": feed_map,
                "back_url": back_url,
            },
        )

    def feeds_page(self, request: Request):
        conn = self.get_db()
        feeds = self._load_subscribed_feeds(conn, order_by="LOWER(COALESCE(title, url))")
        trending = entries.load_trending(conn)
        conn.close()
        return self.templates.TemplateResponse(
            request=request,
            name="feeds.html",
            context={
                "request": request,
                "feeds": feeds,
                "feed_map": catalog.build_feed_map(feeds),
                "trending": trending,
                "q": "",
                "active_feed_id": None,
                "random_enabled": entries.random_enabled_from_request(request),
            },
        )

    def add_feed_page(self, request: Request):
        conn = self.get_db()
        feeds = self._load_subscribed_feeds(conn)
        conn.close()
        return self.templates.TemplateResponse(
            request=request,
            name="add_feed.html",
            context={
                "request": request,
                "feeds": feeds,
                "feed_map": catalog.build_feed_map(feeds),
                "feeds_json": json.dumps(feeds),
                "q": "",
                "active_feed_id": None,
                "random_enabled": entries.random_enabled_from_request(request),
            },
        )

    def discover_page(self, request: Request):
        conn = self.get_db()
        feeds = self._load_subscribed_feeds(conn)
        service_rows = conn.execute(
            """
            SELECT
                f.id,
                f.url,
                COALESCE(f.subscribed, 1) AS subscribed,
                (
                    SELECT COUNT(*)
                    FROM entries e
                    WHERE e.feed_id = f.id
                ) AS entry_count
            FROM feeds f
            """
        ).fetchall()
        conn.close()

        service_feeds = [dict(row) for row in service_rows]
        service_feeds = [apply_effective_subscription(row) for row in service_feeds]
        subscribed = [row["url"] for row in feeds]
        return self.templates.TemplateResponse(
            request=request,
            name="discover.html",
            context={
                "request": request,
                "feeds": feeds,
                "feed_map": catalog.build_feed_map(feeds),
                "catalog_json": json.dumps(catalog.get_full_catalog(self.get_db)),
                "subscribed_json": json.dumps(subscribed),
                "service_feeds_json": json.dumps(service_feeds),
                "q": "",
                "active_feed_id": None,
                "random_enabled": entries.random_enabled_from_request(request),
            },
        )

    def settings_page(self, request: Request):
        conn = self.get_db()
        feeds = self._load_subscribed_feeds(conn)
        conn.close()
        current = {key: self.get_setting(key) for key in self.defaults}
        if "max_entries" not in current:
            current["max_entries"] = self.get_setting("max_entries")
        current.update(get_pipeline_schedule_settings())
        return self.templates.TemplateResponse(
            request=request,
            name="settings.html",
            context={
                "request": request,
                "feeds": feeds,
                "feed_map": catalog.build_feed_map(feeds),
                "settings": current,
                "q": "",
                "active_feed_id": None,
                "random_enabled": entries.random_enabled_from_request(request),
            },
        )

    def stats_page(self, request: Request):
        conn = self.get_db()
        total_articles = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        total_feeds = len(self._load_subscribed_feeds(conn))
        unread_articles = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE COALESCE(read, 0) = 0"
        ).fetchone()[0]
        liked_articles = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE COALESCE(liked, 0) = 1"
        ).fetchone()[0]
        newest_row = conn.execute(
            """
            SELECT published
            FROM entries
            WHERE published IS NOT NULL
              AND TRIM(published) != ''
              AND julianday(published) IS NOT NULL
            ORDER BY julianday(published) DESC, published DESC
            LIMIT 1
            """
        ).fetchone()
        oldest_row = conn.execute(
            """
            SELECT published
            FROM entries
            WHERE published IS NOT NULL
              AND TRIM(published) != ''
              AND julianday(published) IS NOT NULL
            ORDER BY julianday(published) ASC, published ASC
            LIMIT 1
            """
        ).fetchone()
        top_sources_rows = conn.execute(
            """
            SELECT f.id,
                   f.title AS feed_title,
                   f.url AS feed_url,
                   COUNT(e.id) AS article_count
            FROM entries e
            JOIN feeds f ON f.id = e.feed_id
            GROUP BY f.id, f.title, f.url
            ORDER BY article_count DESC
            LIMIT 10
            """
        ).fetchall()
        top_sources = [dict(row) for row in top_sources_rows]

        top_themes: list[dict] = []
        try:
            theme_rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(theme_label), ''), 'World News') AS label,
                       COUNT(*) AS size
                FROM entries
                GROUP BY COALESCE(NULLIF(TRIM(theme_label), ''), 'World News')
                ORDER BY size DESC
                LIMIT 10
                """
            ).fetchall()
            top_themes = [dict(row) for row in theme_rows]
        except Exception:
            top_themes = []

        recent_counts_rows = conn.execute(
            """
            SELECT DATE(published) AS day, COUNT(*) AS count
            FROM entries
            WHERE published IS NOT NULL
              AND DATE(published) >= DATE('now', '-6 day')
            GROUP BY DATE(published)
            ORDER BY day ASC
            """
        ).fetchall()
        recent_counts = [dict(row) for row in recent_counts_rows]
        conn.close()

        return self.templates.TemplateResponse(
            request=request,
            name="stats.html",
            context={
                "request": request,
                "total_articles": total_articles,
                "total_feeds": total_feeds,
                "unread_articles": unread_articles,
                "liked_articles": liked_articles,
                "newest_published": newest_row[0] if newest_row else None,
                "oldest_published": oldest_row[0] if oldest_row else None,
                "top_sources": top_sources,
                "top_themes": top_themes,
                "recent_counts": recent_counts,
                "q": "",
                "random_enabled": entries.random_enabled_from_request(request),
            },
        )
