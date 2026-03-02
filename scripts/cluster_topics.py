import sys
import os
import gc
import logging
import tempfile
from typing import Callable, Optional
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.helpers import get_db, get_setting

logger = logging.getLogger(__name__)

# Steps and their relative weights used to compute overall progress (0–100).
_STEPS = [
    ("Loading model",    5),
    ("Encoding",        55),
    ("Clustering",      15),
    ("Labelling",       10),
    ("Saving",          15),
]
_STEP_NAMES  = [s[0] for s in _STEPS]
_STEP_STARTS = []
_acc = 0
for _, w in _STEPS:
    _STEP_STARTS.append(_acc)
    _acc += w

# Small batch size keeps peak RAM low on the Pi.
# 384-dim float32 × 16 articles = ~24 KB per batch — negligible.
_ENCODE_BATCH = 16


def _make_db_callback(job_id: int) -> Callable[[str, int, int], None]:
    """Return a progress_callback that writes step/progress/total into cluster_jobs."""
    def _cb(step: str, done: int, total: int) -> None:
        step_idx    = _STEP_NAMES.index(step) if step in _STEP_NAMES else 0
        step_weight = _STEPS[step_idx][1]
        base        = _STEP_STARTS[step_idx]
        within      = (done / total * step_weight) if total > 0 else 0
        overall     = int(base + within)
        conn = get_db()
        conn.execute(
            "UPDATE cluster_jobs SET step=?, progress=?, total=100 WHERE id=?",
            (step, overall, job_id),
        )
        conn.commit()
        conn.close()
    return _cb


def start_job() -> int:
    """Insert a new cluster_jobs row and return its id."""
    import datetime
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO cluster_jobs (status, step, progress, total, started_at) "
        "VALUES ('running', 'Loading model', 0, 100, ?)",
        (datetime.datetime.utcnow().isoformat(),),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id


def finish_job(job_id: int, success: bool) -> None:
    import datetime
    status = "done" if success else "error"
    conn = get_db()
    conn.execute(
        "UPDATE cluster_jobs SET status=?, progress=?, finished_at=? WHERE id=?",
        (status, 100 if success else None, datetime.datetime.utcnow().isoformat(), job_id),
    )
    conn.commit()
    conn.close()


def run_cluster_topics(
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> None:
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    def _step(name: str, done: int = 0, total: int = 1) -> None:
        logger.info("%s (%d/%d)", name, done, total)
        if progress_callback:
            progress_callback(name, done, total)

    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, summary FROM entries WHERE title IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        logger.info("No entries to cluster.")
        return

    ids   = [r["id"]   for r in rows]
    texts = [
        ((r["title"] or "") + " " + (r["summary"] or "")).strip()
        for r in rows
    ]
    n = len(ids)

    try:
        k = int(get_setting("num_topic_clusters"))
    except (ValueError, TypeError):
        k = 10
    k = max(1, min(k, n))

    # ── Step 1: load model ───────────────────────────────────────────
    _step("Loading model", 0, 1)
    model = SentenceTransformer("all-MiniLM-L6-v2")
    _step("Loading model", 1, 1)

    # ── Step 2: encode into a temp memmap file ───────────────────────
    # Writing each batch straight to disk means we never hold more than
    # one batch + the final array in RAM at the same time.
    DIM = 384  # all-MiniLM-L6-v2 output dimension
    total_batches = max(1, (n + _ENCODE_BATCH - 1) // _ENCODE_BATCH)

    tmpdir = tempfile.mkdtemp(prefix="rssfeed_emb_")
    mmap_path = os.path.join(tmpdir, "embeddings.npy")
    emb_mmap = np.lib.format.open_memmap(
        mmap_path, mode="w+", dtype="float32", shape=(n, DIM)
    )

    try:
        for i in range(total_batches):
            start = i * _ENCODE_BATCH
            end   = min(start + _ENCODE_BATCH, n)
            batch = texts[start:end]
            emb   = model.encode(
                batch,
                batch_size=_ENCODE_BATCH,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            emb_mmap[start:end] = emb.astype("float32")
            del emb
            _step("Encoding", i + 1, total_batches)

        # Free the model immediately — it's ~90 MB we no longer need
        del model
        gc.collect()

        # Normalise in-place in small chunks to avoid a full second copy
        NORM_CHUNK = 256
        for start in range(0, n, NORM_CHUNK):
            end = min(start + NORM_CHUNK, n)
            emb_mmap[start:end] = normalize(emb_mmap[start:end], norm="l2")
        emb_mmap.flush()

        # ── Step 3: cluster ──────────────────────────────────────────
        # MiniBatchKMeans uses far less peak RAM than full KMeans on large corpora.
        _step("Clustering", 0, 1)
        km = MiniBatchKMeans(
            n_clusters=k,
            random_state=42,
            n_init=3,
            batch_size=min(1024, n),
        )
        labels    = km.fit_predict(emb_mmap)
        centroids = normalize(km.cluster_centers_, norm="l2")
        _step("Clustering", 1, 1)

        # ── Step 4: derive TF-IDF labels ─────────────────────────────
        cluster_texts: dict[int, list[str]] = {i: [] for i in range(k)}
        for text, label in zip(texts, labels):
            cluster_texts[label].append(text)
        del texts  # no longer needed

        tfidf = TfidfVectorizer(max_features=2000, stop_words="english")
        all_texts_flat = [" ".join(cluster_texts[i]) for i in range(k)]
        tfidf_matrix   = tfidf.fit_transform(all_texts_flat)
        feature_names  = tfidf.get_feature_names_out()
        del all_texts_flat, cluster_texts

        cluster_labels: list[str] = []
        for i in range(k):
            row_arr    = tfidf_matrix[i].toarray()[0]
            top_idx    = row_arr.argsort()[-5:][::-1]
            top_terms  = [feature_names[idx] for idx in top_idx if row_arr[idx] > 0]
            cluster_labels.append(", ".join(top_terms) if top_terms else f"Topic {i + 1}")
            _step("Labelling", i + 1, k)
        del tfidf_matrix, tfidf
        gc.collect()

        # ── Step 5: persist ──────────────────────────────────────────
        # Compute cosine scores in chunks to avoid loading full emb_mmap at once
        scores = np.empty(n, dtype="float32")
        SCORE_CHUNK = 512
        for start in range(0, n, SCORE_CHUNK):
            end = min(start + SCORE_CHUNK, n)
            chunk_labels = labels[start:end]
            scores[start:end] = (
                emb_mmap[start:end] * centroids[chunk_labels]
            ).sum(axis=1)

        _step("Saving", 0, 1)
        conn    = get_db()
        cursor  = conn.cursor()
        cursor.executescript("""
            DELETE FROM entry_topics;
            DELETE FROM topic_clusters;
        """)

        for i in range(k):
            cursor.execute(
                "INSERT INTO topic_clusters (id, label, centroid) VALUES (?, ?, ?)",
                (i, cluster_labels[i], centroids[i].astype(np.float32).tobytes()),
            )

        cursor.executemany(
            "INSERT INTO entry_topics (entry_id, cluster_id, score) VALUES (?, ?, ?)",
            [
                (entry_id, int(lbl), float(sc))
                for entry_id, lbl, sc in zip(ids, labels, scores)
            ],
        )

        conn.commit()
        conn.close()
        _step("Saving", 1, 1)
        logger.info("Clustering complete. %d clusters written.", k)

    finally:
        # Always clean up the memmap temp file
        del emb_mmap
        try:
            os.remove(mmap_path)
            os.rmdir(tmpdir)
        except OSError:
            pass


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", type=int, default=None,
                        help="cluster_jobs row to write progress into")
    args = parser.parse_args()

    cb = _make_db_callback(args.job_id) if args.job_id is not None else None
    try:
        run_cluster_topics(progress_callback=cb)
        if args.job_id is not None:
            finish_job(args.job_id, success=True)
    except Exception:
        if args.job_id is not None:
            finish_job(args.job_id, success=False)
        raise
