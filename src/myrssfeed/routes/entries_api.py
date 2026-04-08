import sqlite3
from typing import Callable, Optional

from fastapi import HTTPException, Request

from myrssfeed.api.schemas import EntryOut, EntryVoteUpdate
from myrssfeed.services import entries


class EntryAPIRoutes:
    def __init__(self, get_db: Callable[[], sqlite3.Connection]) -> None:
        self.get_db = get_db

    def register(self, app) -> None:
        app.get("/api/entries", response_model=list[EntryOut])(self.list_entries)
        app.post("/api/entries/{entry_id}/read", status_code=200)(self.mark_read)
        app.post("/api/entries/{entry_id}/like", status_code=200)(self.toggle_like)
        app.post("/api/entries/{entry_id}/vote", status_code=200)(self.set_like)

    def list_entries(
        self,
        request: Request,
        q: Optional[str] = None,
        feed_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
        quality_level: Optional[int] = None,
        days: Optional[str] = None,
        scope: Optional[str] = None,
        themes: Optional[str] = None,
        read_status: Optional[str] = None,
        sort: Optional[str] = None,
    ):
        days_int = entries.parse_days(days)
        sort_val = entries.normalize_sort(sort)
        read_status_val = entries.normalize_read_status(read_status)
        if limit <= 0:
            limit = 100
        if offset < 0:
            offset = 0

        conn = self.get_db()
        try:
            random_seed = entries.random_seed_from_request(request)
            source_scope = entries.normalize_source_scope(scope)
            active_feed_id = feed_id if source_scope == entries.SOURCE_SCOPE_MY else None
            theme_labels = entries.parse_themes_param(themes)
            rows = entries.fetch_ranked_entries(
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
            )
        finally:
            conn.close()
        return rows[offset : offset + limit]

    def mark_read(self, entry_id: int):
        conn = self.get_db()
        try:
            conn.execute("UPDATE entries SET read = 1 WHERE id = ?", (entry_id,))
            conn.commit()
        finally:
            conn.close()
        return {"ok": True}

    def toggle_like(self, entry_id: int):
        conn = self.get_db()
        row = conn.execute(
            "SELECT COALESCE(liked, 0) AS liked FROM entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Entry not found.")
        new_liked = 0 if row["liked"] else 1
        conn.execute("UPDATE entries SET liked = ? WHERE id = ?", (new_liked, entry_id))
        conn.commit()
        conn.close()
        return {"liked": bool(new_liked)}

    def set_like(self, entry_id: int, payload: EntryVoteUpdate):
        conn = self.get_db()
        row = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Entry not found.")
        new_liked = 1 if payload.liked else 0
        conn.execute("UPDATE entries SET liked = ? WHERE id = ?", (new_liked, entry_id))
        conn.commit()
        conn.close()
        return {"liked": bool(new_liked)}
