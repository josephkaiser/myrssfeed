import sqlite3
import os

DB_FILE = os.path.join(os.path.dirname(__file__), "..", "feeds", "rss.db")
DB_FILE = os.path.normpath(DB_FILE)

DEFAULTS: dict[str, str] = {
    "retention_days": "90",
    "theme": "system",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "phi3:mini",
    "digest_max_articles": "50",
    "max_entries": "1000",
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
            title TEXT,
            color TEXT
        );

        CREATE TABLE IF NOT EXISTS entries (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id       INTEGER NOT NULL,
            title         TEXT,
            link          TEXT,
            published     TEXT,
            summary       TEXT,
            thumbnail_url TEXT,
            read          INTEGER DEFAULT 0,
            liked         INTEGER DEFAULT 0,
            score         REAL DEFAULT 0.0,
            viz_x         REAL,
            viz_y         REAL,
            UNIQUE(feed_id, link),
            FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
            USING fts5(title, summary, content='entries', content_rowid='id');

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS viz_themes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            label      TEXT NOT NULL,
            centroid_x REAL NOT NULL,
            centroid_y REAL NOT NULL,
            size       INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_digests (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            content    TEXT NOT NULL,
            model      TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS devices (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            added_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    _migrate_db(conn)
    conn.close()


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Add new columns to existing databases that predate the current schema."""
    entry_cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}
    for col, definition in [
        ("thumbnail_url", "TEXT"),
        ("read", "INTEGER DEFAULT 0"),
        ("liked", "INTEGER DEFAULT 0"),
        ("score", "REAL DEFAULT 0.0"),
        ("viz_x", "REAL"),
        ("viz_y", "REAL"),
    ]:
        if col not in entry_cols:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {col} {definition}")

    feed_cols = {r[1] for r in conn.execute("PRAGMA table_info(feeds)").fetchall()}
    if "color" not in feed_cols:
        conn.execute("ALTER TABLE feeds ADD COLUMN color TEXT")

    conn.commit()


def get_setting(key: str) -> str:
    # Allow docker-compose (and other env-based deployments) to override settings
    # without touching the DB. Env var name: MYRSSFEED_<KEY_UPPER>.
    env_val = os.environ.get(f"MYRSSFEED_{key.upper()}")
    if env_val is not None:
        return env_val
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
