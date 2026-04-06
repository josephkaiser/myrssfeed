import sqlite3
from typing import Any, Callable, Optional

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
        app.get("/api/random-article")(self.get_random_article)

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
        sort: Optional[str] = None,
    ):
        days_int = entries.parse_days(days)
        sort_val = entries.normalize_sort(sort)
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

    def toggle_like(self, entry_id: int, response: Any):
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
        direction = 1 if new_liked else -1
        entries.set_walk_state_cookie(response, entry_id, direction, entries.WALK_INITIAL_STRENGTH)
        return {
            "liked": bool(new_liked),
            "walk": {"anchor_id": entry_id, "direction": direction, "strength": entries.WALK_INITIAL_STRENGTH},
        }

    def set_like(self, entry_id: int, payload: EntryVoteUpdate, response: Any):
        conn = self.get_db()
        row = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Entry not found.")
        new_liked = 1 if payload.liked else 0
        conn.execute("UPDATE entries SET liked = ? WHERE id = ?", (new_liked, entry_id))
        conn.commit()
        conn.close()
        direction = 1 if new_liked else -1
        entries.set_walk_state_cookie(response, entry_id, direction, entries.WALK_INITIAL_STRENGTH)
        return {
            "liked": bool(new_liked),
            "walk": {"anchor_id": entry_id, "direction": direction, "strength": entries.WALK_INITIAL_STRENGTH},
        }

    def get_random_article(
        self,
        request: Request,
        response: Any,
        q: Optional[str] = None,
        feed_id: Optional[int] = None,
        quality_level: Optional[int] = None,
        days: Optional[str] = None,
        scope: Optional[str] = None,
        themes: Optional[str] = None,
        exclude_id: Optional[int] = None,
        exclude_ids: Optional[str] = None,
        walk_anchor_id: Optional[int] = None,
        walk_direction: Optional[int] = None,
        walk_strength: Optional[float] = None,
    ):
        conn = self.get_db()
        try:
            days_int = entries.parse_days(days)
            source_scope = entries.normalize_source_scope(scope)
            theme_labels = entries.parse_themes_param(themes)
            walk_anchor_id, walk_direction, walk_state_strength = entries.read_walk_state(
                request,
                walk_anchor_id=walk_anchor_id,
                walk_direction=walk_direction,
            )
            effective_walk_strength = entries.normalize_walk_strength(walk_strength)
            if effective_walk_strength is None:
                effective_walk_strength = walk_state_strength
            row = entries.fetch_random_entry(
                conn,
                q,
                feed_id,
                quality_level,
                days_int,
                source_scope,
                theme_labels,
                exclude_id=exclude_id,
                exclude_ids=exclude_ids,
                walk_anchor_id=walk_anchor_id,
                walk_direction=walk_direction,
                walk_strength=effective_walk_strength,
            )
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="No matching articles found.")

        if walk_anchor_id is not None and walk_direction is not None:
            next_strength = max(0.0, effective_walk_strength * entries.WALK_DECAY_FACTOR)
            entries.set_walk_state_cookie(response, walk_anchor_id, walk_direction, next_strength)

        article_url = entries.build_url_with_query_params(
            f"/article/{row['id']}",
            {
                "q": q,
                "feed_id": str(feed_id) if feed_id is not None else None,
                "quality_level": str(quality_level) if quality_level is not None else None,
                "days": str(days_int) if days_int is not None else None,
                "scope": source_scope if source_scope != entries.SOURCE_SCOPE_MY else None,
                "themes": ",".join(sorted(theme_labels)) if theme_labels is not None else None,
            },
        )
        return {
            "id": row["id"],
            "article_url": article_url,
            "entry": entries.finalize_entry_row(row),
        }
