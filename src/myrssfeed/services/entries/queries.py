import sqlite3
from typing import AbstractSet, Optional

from myrssfeed.services.catalog import STATIC_CATALOG_URLS

from .constants import (
    SORT_CHRONOLOGICAL,
    SORT_QUALITY_ASC,
    SORT_QUALITY_DESC,
    SOURCE_SCOPE_MY,
)
from .filters import build_entry_filters
from .parsing import build_url_with_query_params
from .ranking import (
    balance_entries_by_theme,
    compute_trending,
    ranking_expr,
)


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
               e.og_image_url,
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
    elif sort == SORT_QUALITY_ASC:
        query += " ORDER BY COALESCE(e.quality_score, 0) ASC, (e.published IS NULL), e.published DESC, e.id DESC"
    else:
        query += " ORDER BY (e.published IS NULL), DATE(e.published) DESC, e.published DESC, base_rank DESC"

    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    return balance_entries_by_theme(rows, random_seed=random_seed if sort == SORT_CHRONOLOGICAL else None)


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
               e.og_image_url,
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
