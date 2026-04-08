import hashlib
import re
from collections import OrderedDict
from collections import deque
from typing import Optional

from myrssfeed.services.catalog import feed_host

WORD_RE = re.compile(r"[A-Za-z0-9']+")
NEUTRAL_SIGNAL = 0.5


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
    entry["theme_label"] = normalize_theme_label(entry.get("theme_label"))
    entry["feed_domain"] = feed_host(feed_url) or None
    return entry


def normalize_theme_label(value: Optional[str]) -> str:
    label = str(value or "").strip()
    return label or "World News"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return default
    if val != val:
        return default
    return val


def _bayesian_blend(value: float, prior: float, count: int, pseudo_count: float) -> float:
    if count <= 0:
        return prior
    total = float(count) + pseudo_count
    return ((value * float(count)) + (prior * pseudo_count)) / max(total, 1.0)


def _confidence_adjusted(value: float, confidence: float, neutral: float = NEUTRAL_SIGNAL) -> float:
    normalized_confidence = _clamp(confidence)
    return neutral + ((value - neutral) * normalized_confidence)


def metadata_confidence(row: dict) -> float:
    title = str(row.get("title") or "").strip()
    summary = str(row.get("summary") or "").strip()
    title_words = len(WORD_RE.findall(title))
    summary_words = len(WORD_RE.findall(summary))

    confidence = 0.16
    if title_words >= 7:
        confidence += 0.2
    elif title_words >= 4:
        confidence += 0.12
    elif title_words >= 2:
        confidence += 0.06

    if summary_words >= 70:
        confidence += 0.4
    elif summary_words >= 35:
        confidence += 0.28
    elif summary_words >= 15:
        confidence += 0.16
    elif summary_words >= 6:
        confidence += 0.08

    if row.get("og_image_url") or row.get("thumbnail_url"):
        confidence += 0.08
    if row.get("link"):
        confidence += 0.04

    return _clamp(confidence)


def quality_signal_available(row: dict) -> bool:
    if str(row.get("assessment_label") or "").strip():
        return True
    return _safe_float(row.get("quality_score"), 0.0) > 0.0


def _feed_prior(
    feed_stat: Optional[dict],
    global_stat: Optional[dict],
    *,
    has_personalization: bool,
) -> float:
    global_stat = global_stat or {}
    feed_stat = feed_stat or {}

    global_quality = _safe_float(global_stat.get("avg_quality"), NEUTRAL_SIGNAL)
    global_score = _safe_float(global_stat.get("avg_score"), NEUTRAL_SIGNAL) if has_personalization else NEUTRAL_SIGNAL
    global_like_rate = _safe_float(global_stat.get("like_rate"), 0.0)

    quality_count = int(feed_stat.get("quality_count") or 0)
    recent_quality_count = int(feed_stat.get("recent_quality_count") or 0)
    avg_quality = _safe_float(feed_stat.get("avg_quality"), global_quality)
    recent_quality = _safe_float(feed_stat.get("recent_quality"), avg_quality if quality_count > 0 else global_quality)
    avg_score = _safe_float(feed_stat.get("avg_score"), global_score)
    like_rate = _safe_float(feed_stat.get("like_rate"), global_like_rate)

    long_term_quality = _bayesian_blend(avg_quality, global_quality, quality_count, 10.0)
    recent_quality_prior = _bayesian_blend(recent_quality, long_term_quality, recent_quality_count, 4.0)
    personalization_prior = _bayesian_blend(avg_score, global_score, int(feed_stat.get("entry_count") or 0), 12.0)
    engagement_prior = _bayesian_blend(like_rate, global_like_rate, int(feed_stat.get("entry_count") or 0), 24.0)

    return _clamp(
        (0.62 * recent_quality_prior)
        + (0.2 * personalization_prior)
        + (0.18 * engagement_prior)
    )


def annotate_entries_for_ranking(
    entries: list[dict],
    feed_stats: Optional[dict[int, dict]] = None,
    global_stats: Optional[dict] = None,
) -> list[dict]:
    if not entries:
        return []

    feed_stats = feed_stats or {}
    global_stats = global_stats or {}
    has_personalization = int(global_stats.get("liked_count") or 0) > 0

    annotated: list[dict] = []
    for row in entries:
        row_copy = dict(row)
        confidence = metadata_confidence(row_copy)
        quality_raw = (
            _safe_float(row_copy.get("quality_score"), NEUTRAL_SIGNAL)
            if quality_signal_available(row_copy)
            else NEUTRAL_SIGNAL
        )
        quality_signal = _confidence_adjusted(quality_raw, 0.42 + (0.58 * confidence))

        if has_personalization:
            score_raw = _safe_float(row_copy.get("score"), NEUTRAL_SIGNAL)
            personalization_signal = _confidence_adjusted(score_raw, 0.24 + (0.56 * confidence))
        else:
            personalization_signal = NEUTRAL_SIGNAL

        feed_id = int(row_copy.get("feed_id") or 0)
        feed_prior = _feed_prior(
            feed_stats.get(feed_id),
            global_stats,
            has_personalization=has_personalization,
        )

        image_bonus = 0.04 if row_copy.get("og_image_url") or row_copy.get("thumbnail_url") else 0.0
        liked_boost = 0.06 if int(row_copy.get("liked") or 0) else 0.0

        row_copy["metadata_confidence"] = confidence
        row_copy["feed_prior"] = feed_prior
        row_copy["base_rank"] = _clamp(
            (0.44 * quality_signal)
            + (0.18 * personalization_signal)
            + (0.22 * feed_prior)
            + (0.12 * confidence)
            + image_bonus
            + liked_boost
        )
        annotated.append(row_copy)

    return annotated


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


def balance_entries_by_theme(entries: list[dict], random_seed: Optional[int] = None) -> list[dict]:
    if not entries:
        return []

    recency_factor = 0.74 if random_seed is not None else 0.86
    rank_factor = 0.12 if random_seed is not None else 0.14
    noise_factor = 0.18 if random_seed is not None else 0.0

    grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
    for row in entries:
        row_copy = dict(row)
        row_copy["theme_label"] = normalize_theme_label(row_copy.get("theme_label"))
        grouped.setdefault(row_copy["theme_label"], []).append(row_copy)

    buckets: "OrderedDict[str, deque[dict]]" = OrderedDict()
    for label, rows in grouped.items():
        diversified = apply_source_diversity(
            rows,
            random_seed=random_seed,
            recency_factor=recency_factor,
            rank_factor=rank_factor,
            noise_factor=noise_factor,
            recent_window=4,
            repeat_penalty=0.22,
            streak_penalty=0.42,
            novelty_bonus=0.08,
        )
        buckets[label] = deque(diversified)

    ranked: list[dict] = []
    while True:
        appended = False
        for bucket in buckets.values():
            if not bucket:
                continue
            ranked.append(bucket.popleft())
            appended = True
        if not appended:
            break

    return ranked


def group_entries_by_theme(entries: list[dict]) -> list[dict]:
    grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
    for entry in entries:
        label = normalize_theme_label(entry.get("theme_label"))
        grouped.setdefault(label, []).append(entry)
    return [{"label": label, "entries": rows} for label, rows in grouped.items()]


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
