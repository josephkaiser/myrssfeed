# Requires: scikit-learn>=1.5.0, numpy>=1.26.0
import gc
import re
import logging

from myrssfeed.utils.helpers import get_db

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text or '')


def _ensure_schema(conn) -> None:
    """Add viz columns to entries if missing; create viz_themes table."""
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(entries)")
    existing_columns = {row["name"] for row in cursor.fetchall()}

    if "viz_x" not in existing_columns:
        cursor.execute("ALTER TABLE entries ADD COLUMN viz_x REAL")
    if "viz_y" not in existing_columns:
        cursor.execute("ALTER TABLE entries ADD COLUMN viz_y REAL")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viz_themes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            label      TEXT NOT NULL,
            centroid_x REAL NOT NULL,
            centroid_y REAL NOT NULL,
            size       INTEGER NOT NULL
        )
    """)
    conn.commit()


def run_visualization() -> None:
    """Recompute 2D topic layout and theme labels for all entries."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import TruncatedSVD
    from sklearn.manifold import TSNE
    from sklearn.cluster import KMeans
    import numpy as np

    logger.info("Visualization: starting")

    conn = get_db()
    _ensure_schema(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT id, title, summary FROM entries")
    rows = cursor.fetchall()
    entries = [(row["id"], row["title"] or "", row["summary"] or "") for row in rows]

    if len(entries) < 10:
        logger.warning(
            "Visualization: only %d entries found (minimum 10 required). Skipping.",
            len(entries),
        )
        conn.execute("UPDATE entries SET viz_x = NULL, viz_y = NULL")
        conn.commit()
        conn.close()
        return

    ids = [e[0] for e in entries]
    texts = [e[1] + " " + _strip_html(e[2]) for e in entries]

    # TF-IDF
    vectorizer = TfidfVectorizer(max_features=5000, stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(texts)
    feature_names = vectorizer.get_feature_names_out()

    # SVD — reduce to 50 dims
    n_svd = min(50, tfidf_matrix.shape[1] - 1, len(entries) - 1)
    svd = TruncatedSVD(n_components=n_svd, random_state=42)
    svd_coords = svd.fit_transform(tfidf_matrix)
    logger.info("Visualization: SVD done (%d entries, %d components)", len(entries), n_svd)

    # t-SNE — reduce to 2D
    perplexity = min(30, max(5, len(entries) // 10))
    tsne = TSNE(n_components=2, random_state=42, perplexity=perplexity)
    tsne_coords = tsne.fit_transform(svd_coords)
    logger.info("Visualization: t-SNE done (perplexity=%d)", perplexity)

    # KMeans on SVD space
    n_clusters = min(8, len(entries) // 10 + 1)
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    cluster_labels = kmeans.fit_predict(svd_coords)

    # Extract theme labels and centroids per cluster
    tfidf_dense = tfidf_matrix.toarray()
    themes = []
    for cluster_id in range(n_clusters):
        mask = cluster_labels == cluster_id
        cluster_size = int(mask.sum())

        if cluster_size == 0:
            logger.warning("Visualization: cluster %d is empty, skipping", cluster_id)
            continue

        cluster_tfidf_sum = tfidf_dense[mask].sum(axis=0)
        top_indices = cluster_tfidf_sum.argsort()[-3:][::-1]
        top_words = [feature_names[i] for i in top_indices]
        label = " ".join(top_words)

        cluster_tsne = tsne_coords[mask]
        centroid_x = float(cluster_tsne[:, 0].mean())
        centroid_y = float(cluster_tsne[:, 1].mean())

        themes.append((label, centroid_x, centroid_y, cluster_size))

    logger.info("Visualization: %d themes extracted", len(themes))

    # Write viz_x, viz_y to entries
    updates = [
        (float(tsne_coords[i, 0]), float(tsne_coords[i, 1]), entry_id)
        for i, entry_id in enumerate(ids)
    ]
    conn.executemany(
        "UPDATE entries SET viz_x = ?, viz_y = ? WHERE id = ?",
        updates,
    )

    # Clear and repopulate viz_themes
    conn.execute("DELETE FROM viz_themes")
    conn.executemany(
        "INSERT INTO viz_themes (label, centroid_x, centroid_y, size) VALUES (?, ?, ?, ?)",
        themes,
    )

    conn.commit()
    conn.close()

    # Explicitly free large arrays so memory is returned to the OS before
    # the next pipeline stage requests LLM resources.
    del tfidf_matrix, tfidf_dense, svd_coords, tsne_coords, cluster_labels
    gc.collect()

    logger.info("Visualization: done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_visualization()
