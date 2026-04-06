from typing import AbstractSet, Optional

from myrssfeed.services.catalog import STATIC_CATALOG_URLS

from .constants import DATE_RANGE_DAYS, SOURCE_SCOPE_DISCOVER, SOURCE_SCOPE_MY


def source_scope_clause(
    source_scope: str,
    static_catalog_urls: AbstractSet[str] = STATIC_CATALOG_URLS,
) -> tuple[str, list]:
    if source_scope == SOURCE_SCOPE_DISCOVER and static_catalog_urls:
        urls = sorted(static_catalog_urls)
        placeholders = ", ".join("?" for _ in urls)
        return f"(COALESCE(f.subscribed, 1) = 1 OR f.url IN ({placeholders}))", urls
    return "(COALESCE(f.subscribed, 1) = 1)", []


def build_entry_filters(
    q: Optional[str],
    feed_id: Optional[int],
    quality_level: Optional[int],
    days_int: Optional[int],
    source_scope: str,
    theme_labels: Optional[set[str]],
    static_catalog_urls: AbstractSet[str] = STATIC_CATALOG_URLS,
) -> tuple[list[str], list]:
    filters: list[str] = []
    params: list = []

    scope_clause, scope_params = source_scope_clause(source_scope, static_catalog_urls)
    filters.append(scope_clause)
    params.extend(scope_params)

    if q and q.strip():
        query_text = q.strip()
        filters.append("(e.title LIKE ? OR e.summary LIKE ?)")
        params += [f"%{query_text}%", f"%{query_text}%"]
    if feed_id is not None and source_scope == SOURCE_SCOPE_MY:
        filters.append("e.feed_id = ?")
        params.append(feed_id)
    if days_int is not None and days_int in DATE_RANGE_DAYS:
        filters.append("(e.published IS NOT NULL AND date(e.published) >= date('now', ?))")
        params.append(f"-{days_int} days")

    if quality_level is not None:
        try:
            level = int(quality_level)
        except (TypeError, ValueError):
            level = 1
        level = max(0, min(3, level))
        if level == 0:
            min_title, min_summary = 5, 20
        elif level == 1:
            min_title, min_summary = 10, 40
        elif level == 2:
            min_title, min_summary = 20, 80
        else:
            min_title, min_summary = 30, 120

        quality_threshold = {0: 0.25, 1: 0.35, 2: 0.5, 3: 0.65}.get(level, 0.35)
        filters.append(
            "("
            "e.link IS NOT NULL AND TRIM(e.link) != '' AND ("
            "COALESCE(e.quality_score, 0) >= ? OR "
            "LENGTH(COALESCE(e.title, '')) >= ? OR "
            "LENGTH(COALESCE(e.summary, '')) >= ?"
            ")"
            ")"
        )
        params.extend([quality_threshold, min_title, min_summary])

    if theme_labels is not None:
        if theme_labels:
            placeholders = ", ".join("?" for _ in theme_labels)
            filters.append(f"COALESCE(e.theme_label, 'World News') IN ({placeholders})")
            params.extend(list(theme_labels))
        else:
            filters.append("1=0")

    return filters, params
