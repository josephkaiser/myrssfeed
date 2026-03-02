import sqlite3
import os

DB_FILE = os.path.join(os.path.dirname(__file__), "..", "feeds", "rss.db")
DB_FILE = os.path.normpath(DB_FILE)

DEFAULTS: dict[str, str] = {
    "retention_days": "90",
    "theme": "system",
    "num_topic_clusters": "10",
    "max_entries_to_cluster": "2000",  # 0 = no cap
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2:1b",
}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS feeds (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            url   TEXT UNIQUE NOT NULL,
            title TEXT
        );

        CREATE TABLE IF NOT EXISTS entries (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id   INTEGER NOT NULL,
            title     TEXT,
            link      TEXT,
            published TEXT,
            summary   TEXT,
            UNIQUE(feed_id, link),
            FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
            USING fts5(title, summary, content='entries', content_rowid='id');

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS topic_clusters (
            id      INTEGER PRIMARY KEY,
            label   TEXT,
            centroid BLOB
        );

        CREATE TABLE IF NOT EXISTS entry_topics (
            entry_id   INTEGER NOT NULL,
            cluster_id INTEGER NOT NULL,
            score      REAL,
            PRIMARY KEY (entry_id, cluster_id),
            FOREIGN KEY (entry_id)   REFERENCES entries(id) ON DELETE CASCADE,
            FOREIGN KEY (cluster_id) REFERENCES topic_clusters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cluster_jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            status      TEXT NOT NULL DEFAULT 'pending',
            step        TEXT,
            progress    INTEGER NOT NULL DEFAULT 0,
            total       INTEGER NOT NULL DEFAULT 0,
            started_at  TEXT,
            finished_at TEXT,
            error_log   TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_digests (
            date       TEXT PRIMARY KEY,
            summary    TEXT NOT NULL,
            model      TEXT,
            created_at TEXT NOT NULL
        );
    """)
    # Migrate existing databases that pre-date the error_log column.
    try:
        cursor.execute("ALTER TABLE cluster_jobs ADD COLUMN error_log TEXT")
    except Exception:
        pass  # column already exists
    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        return row["value"]
    return DEFAULTS.get(key, "")


def set_setting(key: str, value: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()
