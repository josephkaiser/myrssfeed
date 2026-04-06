import random
import sqlite3
from typing import AbstractSet, Optional

from myrssfeed.services.catalog import STATIC_CATALOG_URLS

from .constants import (
    SORT_CHRONOLOGICAL,
    SORT_QUALITY_ASC,
    SORT_QUALITY_DESC,
    SOURCE_SCOPE_MY,
    WALK_CANDIDATE_LIMIT,
    WALK_INITIAL_STRENGTH,
)
from .filters import build_entry_filters
from .parsing import (
    build_url_with_query_params,
    normalize_walk_direction,
    normalize_walk_strength,
    parse_int,
    parse_int_list,
)
from .ranking import (
    apply_daily_source_diversity,
    compute_trending,
    finalize_entry_row,
    ranking_expr,
)
from .walk import pick_walk_candidate


def fetch_ranked_entries(
    conn: sqlite3.Connection,
    random_seed: Optional[int],
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
    sort: str = SORT_CHRONOLOGICAL,
    static_catalog_urls: AbstractSet[str] = STATIC_CATALOG_URLS,
) -> list[dict]:
    rank_sql = ranking_expr(None)
    query = f"""
        SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
               e.title, e.link, e.published, DATE(e.published) AS published_day, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score,
               COALESCE(e.quality_score, 0.0) AS quality_score,
               e.assessment_label,
               e.assessment_label_color,
               e.theme_label,
               e.theme_label_color,
               {rank_sql} AS base_rank
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
    """
    filters, params = build_entry_filters(
        q,
        feed_id,
        quality_level,
        days_int,
        source_scope,
        theme_labels,
        static_catalog_urls,
    )
    if filters:
        query += " WHERE " + " AND ".join(filters)
    if sort == SORT_QUALITY_DESC:
        query += " ORDER BY COALESCE(e.quality_score, 0) DESC, (e.published IS NULL), e.published DESC, e.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    if sort == SORT_QUALITY_ASC:
        query += " ORDER BY COALESCE(e.quality_score, 0) ASC, (e.published IS NULL), e.published DESC, e.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    query += " ORDER BY (e.published IS NULL), DATE(e.published) DESC, e.published DESC, base_rank DESC"
    rows = conn.execute(query, params).fetchall()
    random_enabled = random_seed is not None
    recency_factor = 0.3 if random_enabled else 0.8
    rank_factor = 0.2 if random_enabled else 0.2
    noise_factor = 0.5 if random_enabled else 0.0
    return apply_daily_source_diversity(
        [dict(row) for row in rows],
        random_seed=random_seed,
        recency_factor=recency_factor,
        rank_factor=rank_factor,
        noise_factor=noise_factor,
    )


def article_neighbor_urls(
    conn: sqlite3.Connection,
    entry_id: int,
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
    sort: str = SORT_CHRONOLOGICAL,
    static_catalog_urls: AbstractSet[str] = STATIC_CATALOG_URLS,
) -> tuple[Optional[str], Optional[str]]:
    rows = fetch_ranked_entries(
        conn,
        None,
        q,
        feed_id,
        quality_level,
        days_int,
        source_scope,
        theme_labels,
        sort,
        static_catalog_urls=static_catalog_urls,
    )
    if not rows:
        return None, None

    current_index = next((idx for idx, row in enumerate(rows) if int(row.get("id") or 0) == entry_id), None)
    if current_index is None:
        return None, None

    context_params = {
        "q": q,
        "feed_id": str(feed_id) if feed_id is not None else None,
        "quality_level": str(quality_level) if quality_level is not None else None,
        "days": str(days_int) if days_int is not None else None,
        "scope": source_scope if source_scope != SOURCE_SCOPE_MY else None,
        "themes": ",".join(sorted(theme_labels)) if theme_labels is not None else None,
        "sort": sort if sort != SORT_CHRONOLOGICAL else None,
    }

    previous_url = None
    next_url = None
    if current_index > 0:
        previous_url = build_url_with_query_params(f"/article/{rows[current_index - 1]['id']}", context_params)
    if current_index + 1 < len(rows):
        next_url = build_url_with_query_params(f"/article/{rows[current_index + 1]['id']}", context_params)
    return previous_url, next_url


def load_trending(conn: sqlite3.Connection) -> list[dict]:
    query = """
        SELECT e.id, e.feed_id, f.title AS feed_title,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score,
               e.assessment_label,
               e.assessment_label_color
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        ORDER BY e.published DESC, """
    query += ranking_expr(None, 0.7, 0.3, 0.0)
    query += " DESC LIMIT 200"
    rows = conn.execute(query).fetchall()
    return compute_trending([dict(row) for row in rows])


def fetch_random_entry(
    conn: sqlite3.Connection,
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
    exclude_id: Optional[int] = None,
    exclude_ids: Optional[str] = None,
    walk_anchor_id: Optional[int] = None,
    walk_direction: Optional[int] = None,
    walk_strength: Optional[float] = None,
    static_catalog_urls: AbstractSet[str] = STATIC_CATALOG_URLS,
) -> Optional[dict]:
    filters, params = build_entry_filters(
        q,
        feed_id,
        quality_level,
        days_int,
        source_scope,
        theme_labels,
        static_catalog_urls,
    )
    excluded_ids = parse_int_list(exclude_ids)
    if exclude_id is not None:
        excluded_ids.add(int(exclude_id))
    if excluded_ids:
        excluded_list = sorted(excluded_ids)
        placeholders = ", ".join("?" for _ in excluded_list)
        filters.append(f"e.id NOT IN ({placeholders})")
        params.extend(excluded_list)

    base_query = "FROM entries e JOIN feeds f ON f.id = e.feed_id"
    where_clause = " WHERE " + " AND ".join(filters) if filters else ""

    total = conn.execute(f"SELECT COUNT(*) {base_query}{where_clause}", params).fetchone()[0]
    if not total:
        return None

    anchor_id = parse_int(walk_anchor_id)
    direction = normalize_walk_direction(walk_direction)
    strength = normalize_walk_strength(walk_strength)
    if strength is None:
        strength = WALK_INITIAL_STRENGTH if anchor_id is not None and direction is not None else 0.0

    if anchor_id is not None and direction is not None:
        anchor_row = conn.execute(
            """
            SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
                   e.title, e.link, e.published, e.summary,
                   e.thumbnail_url,
                   COALESCE(e.read, 0) AS read,
                   COALESCE(e.liked, 0) AS liked,
                   COALESCE(e.score, 0.0) AS score,
                   COALESCE(e.quality_score, 0.0) AS quality_score,
                   e.assessment_label,
                   e.assessment_label_color
            FROM entries e
            JOIN feeds f ON f.id = e.feed_id
            WHERE e.id = ?
            """,
            (anchor_id,),
        ).fetchone()
        if anchor_row:
            walk_rows = conn.execute(
                f"""
                SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
                       e.title, e.link, e.published, e.summary,
                       e.thumbnail_url,
                       COALESCE(e.read, 0) AS read,
                       COALESCE(e.liked, 0) AS liked,
                       COALESCE(e.score, 0.0) AS score,
                       COALESCE(e.quality_score, 0.0) AS quality_score,
                       e.assessment_label,
                       e.assessment_label_color
                {base_query}
                {where_clause}
                ORDER BY (e.published IS NULL), DATE(e.published) DESC, e.published DESC, e.id DESC
                LIMIT ?
                """,
                params + [WALK_CANDIDATE_LIMIT],
            ).fetchall()
            chosen = pick_walk_candidate([dict(row) for row in walk_rows], dict(anchor_row), direction, strength)
            if chosen:
                return chosen

    offset = random.randrange(total)
    row = conn.execute(
        f"""
        SELECT e.id, e.feed_id, f.title AS feed_title, f.url AS feed_url,
               e.title, e.link, e.published, e.summary,
               e.thumbnail_url,
               COALESCE(e.read, 0) AS read,
               COALESCE(e.liked, 0) AS liked,
               COALESCE(e.score, 0.0) AS score,
               COALESCE(e.quality_score, 0.0) AS quality_score,
               e.assessment_label,
               e.assessment_label_color
        {base_query}
        {where_clause}
        ORDER BY (e.published IS NULL), DATE(e.published) DESC, e.published DESC, e.id DESC
        LIMIT 1 OFFSET ?
        """,
        params + [offset],
    ).fetchone()
    return dict(row) if row else None
