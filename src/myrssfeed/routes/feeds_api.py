import sqlite3
from typing import Callable, Optional

from fastapi import HTTPException

from myrssfeed.api.schemas import CatalogRemoveRequest, FeedCreate, FeedOut, FeedUpdate
from myrssfeed.services import catalog
from myrssfeed.services.subscriptions import (
    apply_effective_subscription,
    clear_pending_subscription_change,
    filter_subscribed_rows,
    queue_subscription_change,
)


class FeedAPIRoutes:
    def __init__(
        self,
        get_db: Callable[[], sqlite3.Connection],
        is_pipeline_running: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.get_db = get_db
        self.is_pipeline_running = is_pipeline_running or (lambda: False)

    def register(self, app) -> None:
        app.get("/api/feeds", response_model=list[FeedOut])(self.list_feeds)
        app.post("/api/feeds", response_model=FeedOut, status_code=201)(self.add_feed)
        app.patch("/api/feeds/{feed_id}", response_model=FeedOut)(self.update_feed)
        app.delete("/api/feeds/{feed_id}")(self.delete_feed)
        app.post("/api/feeds/{feed_id}/subscribe", response_model=FeedOut)(self.subscribe_feed)
        app.delete("/api/feeds/{feed_id}/service", status_code=204)(self.remove_feed_from_service)
        app.delete("/api/catalog", status_code=204)(self.remove_from_catalog)

    def list_feeds(self):
        conn = self.get_db()
        try:
            rows = conn.execute(
                """
                SELECT id, url, title, color, COALESCE(subscribed, 1) AS subscribed
                FROM feeds
                ORDER BY title
                """
            ).fetchall()
        finally:
            conn.close()
        return filter_subscribed_rows([dict(row) for row in rows])

    def add_feed(self, feed: FeedCreate):
        conn = self.get_db()
        url = str(feed.url)
        title = feed.title or None
        existing = conn.execute(
            "SELECT id, url, title, color FROM feeds WHERE url = ?",
            (url,),
        ).fetchone()
        if existing:
            clear_pending_subscription_change(existing["id"])
            conn.execute(
                "UPDATE feeds SET subscribed = 1, title = COALESCE(?, title) WHERE id = ?",
                (title, existing["id"]),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, url, title, color FROM feeds WHERE id = ?",
                (existing["id"],),
            ).fetchone()
            conn.close()
            catalog.add_to_user_catalog(self.get_db, url, title or row["title"] or url)
            return dict(row)
        try:
            row = conn.execute(
                "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1) RETURNING id, url, title, color",
                (url, title),
            ).fetchone()
            conn.commit()
        except Exception as exc:
            conn.close()
            raise HTTPException(status_code=409, detail="Feed URL already exists.") from exc
        conn.close()
        catalog.add_to_user_catalog(self.get_db, url, title or url)
        return dict(row)

    def update_feed(self, feed_id: int, payload: FeedUpdate):
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update.")
        conn = self.get_db()
        try:
            cols = ", ".join(f"{key} = ?" for key in updates.keys())
            values = list(updates.values()) + [feed_id]
            row = conn.execute(
                f"UPDATE feeds SET {cols} WHERE id = ? RETURNING id, url, title, color, COALESCE(subscribed, 1) AS subscribed",
                values,
            ).fetchone()
            conn.commit()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Feed not found.")
        return dict(row)

    def delete_feed(self, feed_id: int):
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT id, url, title, color, COALESCE(subscribed, 1) AS subscribed FROM feeds WHERE id = ?",
                (feed_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Feed not found.")
            if self.is_pipeline_running():
                queue_subscription_change(feed_id, False)
                return {
                    "status": "queued",
                    "queued": True,
                    "message": "Feed removal queued for the next refresh.",
                    "feed": apply_effective_subscription(dict(row)),
                }
            conn.execute("UPDATE feeds SET subscribed = 0 WHERE id = ?", (feed_id,))
            conn.commit()
            clear_pending_subscription_change(feed_id)
        finally:
            conn.close()
        return {
            "status": "removed",
            "queued": False,
            "message": "Removed from subscriptions.",
        }

    def subscribe_feed(self, feed_id: int):
        conn = self.get_db()
        queued = False
        try:
            if self.is_pipeline_running():
                row = conn.execute(
                    """
                    SELECT id, url, title, color, COALESCE(subscribed, 1) AS subscribed
                    FROM feeds
                    WHERE id = ?
                    """,
                    (feed_id,),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Feed not found.")
                queue_subscription_change(feed_id, True)
                row = apply_effective_subscription(dict(row))
                queued = True
            else:
                row = conn.execute(
                    "UPDATE feeds SET subscribed = 1 WHERE id = ? RETURNING id, url, title, color, COALESCE(subscribed, 1) AS subscribed",
                    (feed_id,),
                ).fetchone()
                conn.commit()
                clear_pending_subscription_change(feed_id)
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Feed not found.")
        catalog.add_to_user_catalog(self.get_db, row["url"], row["title"] or row["url"])
        return dict(row) if not queued else row

    def remove_feed_from_service(self, feed_id: int):
        conn = self.get_db()
        try:
            feed = conn.execute("SELECT id, url FROM feeds WHERE id = ?", (feed_id,)).fetchone()
            if not feed:
                raise HTTPException(status_code=404, detail="Feed not found.")
            conn.execute("DELETE FROM entries WHERE feed_id = ?", (feed_id,))
            conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
            try:
                conn.execute("DELETE FROM user_catalog WHERE url = ?", (feed["url"],))
            except Exception:
                pass
            conn.commit()
        finally:
            conn.close()

    def remove_from_catalog(self, payload: CatalogRemoveRequest):
        url = str(payload.url)
        conn = self.get_db()
        try:
            try:
                conn.execute("DELETE FROM user_catalog WHERE url = ?", (url,))
            except Exception:
                pass
            conn.execute("UPDATE feeds SET subscribed = 0 WHERE url = ?", (url,))
            conn.commit()
        finally:
            conn.close()
