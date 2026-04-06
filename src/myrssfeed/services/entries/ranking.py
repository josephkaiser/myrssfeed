import hashlib
from collections import deque
from typing import Optional

from myrssfeed.services.catalog import feed_host


def ranking_expr(
    random_seed: Optional[int],
    score_weight: float = 0.6,
    quality_weight: float = 0.3,
    random_weight: float = 0.1,
) -> str:
    expr = f"(COALESCE(e.score,0)*{score_weight} + COALESCE(e.quality_score,0)*{quality_weight}"
    if random_seed is not None:
        seed = abs(int(random_seed))
        expr += (
            " + ("
            f"abs((COALESCE(e.id, 0) * 1103515245 + COALESCE(e.feed_id, 0) * 12345 + {seed}) % 2147483647)"
            " / 2147483647.0)"
            f" * {random_weight}"
        )
    expr += ")"
    return expr


def finalize_entry_row(row: dict) -> dict:
    entry = dict(row)
    feed_url = entry.pop("feed_url", None)
    entry.pop("base_rank", None)
    entry.pop("published_day", None)
    entry.pop("effective_rank", None)
    entry["feed_domain"] = feed_host(feed_url) or None
    return entry


def seeded_noise(seed: Optional[int], row: dict) -> float:
    if seed is None:
        return 0.0
    payload = "|".join(
        [
            str(abs(int(seed))),
            str(row.get("id") or ""),
            str(row.get("feed_id") or ""),
            str(row.get("published") or ""),
            str(row.get("title") or ""),
        ]
    ).encode("utf-8", errors="ignore")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def source_key(row: dict) -> str:
    host = feed_host(row.get("feed_url"))
    if host:
        return host
    feed_id = int(row.get("feed_id") or 0)
    if feed_id:
        return f"feed:{feed_id}"
    return f"row:{row.get('id', '')}"


def apply_source_diversity(
    entries: list[dict],
    random_seed: Optional[int] = None,
    recent_window: int = 6,
    repeat_penalty: float = 0.18,
    streak_penalty: float = 0.35,
    novelty_bonus: float = 0.05,
    recency_factor: float = 0.8,
    rank_factor: float = 0.2,
    noise_factor: float = 0.0,
) -> list[dict]:
    if len(entries) <= 1:
        return [finalize_entry_row(entries[0])] if entries else []

    total = len(entries)
    pool = []
    for idx, row in enumerate(entries):
        row_copy = dict(row)
        recency_weight = (total - idx) / total
        base_rank = float(row_copy.get("base_rank") or 0.0)
        noise = seeded_noise(random_seed, row_copy)
        row_copy["effective_rank"] = (
            (recency_factor * recency_weight)
            + (rank_factor * base_rank)
            + (noise_factor * noise)
        )
        pool.append((idx, row_copy))

    ranked: list[dict] = []
    recent = deque()
    recent_counts: dict[str, int] = {}
    last_source: Optional[str] = None
    streak = 0

    while pool:
        source_keys = {source_key(row) for _, row in pool}
        best_pos = 0
        best_adjusted = None
        best_base = None
        best_original_idx = None

        for pos, (original_idx, row) in enumerate(pool):
            row_source_key = source_key(row)
            base_rank = float(row.get("effective_rank") or row.get("base_rank") or 0.0)
            repeat_count = recent_counts.get(row_source_key, 0)
            adjusted = base_rank - (repeat_penalty * repeat_count)
            if row_source_key == last_source:
                adjusted -= streak_penalty * streak
            elif repeat_count == 0 and len(source_keys) > 1:
                adjusted += novelty_bonus

            if (
                best_adjusted is None
                or adjusted > best_adjusted
                or (adjusted == best_adjusted and base_rank > (best_base if best_base is not None else float("-inf")))
                or (
                    adjusted == best_adjusted
                    and base_rank == best_base
                    and original_idx < (best_original_idx if best_original_idx is not None else original_idx)
                )
            ):
                best_pos = pos
                best_adjusted = adjusted
                best_base = base_rank
                best_original_idx = original_idx

        _, chosen = pool.pop(best_pos)
        ranked.append(finalize_entry_row(chosen))

        chosen_source_key = source_key(chosen)
        if chosen_source_key:
            recent.append(chosen_source_key)
            recent_counts[chosen_source_key] = recent_counts.get(chosen_source_key, 0) + 1
            if len(recent) > recent_window:
                old = recent.popleft()
                recent_counts[old] -= 1
                if recent_counts[old] <= 0:
                    del recent_counts[old]

        if chosen_source_key == last_source:
            streak += 1
        else:
            last_source = chosen_source_key
            streak = 1

    return ranked


def apply_daily_source_diversity(
    entries: list[dict],
    random_seed: Optional[int] = None,
    recency_factor: float = 0.8,
    rank_factor: float = 0.2,
    noise_factor: float = 0.0,
) -> list[dict]:
    if not entries:
        return []

    ranked: list[dict] = []
    day_groups: list[list[dict]] = []
    current_day = None
    current_group: list[dict] = []

    for row in entries:
        day = row.get("published_day")
        if day != current_day and current_group:
            day_groups.append(current_group)
            current_group = []
        current_day = day
        current_group.append(row)

    if current_group:
        day_groups.append(current_group)

    for group in day_groups:
        ranked.extend(
            apply_source_diversity(
                group,
                random_seed=random_seed,
                recency_factor=recency_factor,
                rank_factor=rank_factor,
                noise_factor=noise_factor,
            )
        )

    return ranked


def compute_trending(entries: list[dict], limit: int = 10) -> list[dict]:
    if not entries:
        return []

    total = len(entries)
    ranked = []
    for idx, entry in enumerate(entries):
        recency_weight = (total - idx) / total
        score = float(entry.get("score") or 0.0)
        combined = 0.7 * recency_weight + 0.3 * score
        ranked.append((combined, entry))

    ranked.sort(key=lambda item: item[0], reverse=True)

    per_feed_cap = 2
    feed_counts: dict[int, int] = {}
    trending: list[dict] = []
    for _, entry in ranked:
        feed_id = int(entry.get("feed_id") or 0)
        if feed_id:
            if feed_counts.get(feed_id, 0) >= per_feed_cap:
                continue
            feed_counts[feed_id] = feed_counts.get(feed_id, 0) + 1
        trending.append(entry)
        if len(trending) >= limit:
            break

    return trending
