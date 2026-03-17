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
    # Scraper limits
    "scrape_enabled": "true",
    "scrape_timeout_seconds": "6",
    "scrape_max_bytes": str(512 * 1024),
    "scrape_max_per_run": "40",
    # Pipeline scheduler & status (for manual/automatic refresh jobs)
    # Frequency: "off" | "10m" | "hourly" | "daily"
    "pipeline_schedule_frequency": "daily",
    # Time of day (local) for "daily" / "hourly" anchors, format HH:MM (24h)
    "pipeline_schedule_time": "06:00",
    # Newsletter mailbox polling
    "newsletter_enabled": "false",
    "newsletter_imap_host": "",
    "newsletter_imap_port": "993",
    "newsletter_imap_username": "",
    "newsletter_imap_password": "",
    "newsletter_imap_folder": "INBOX",
    "newsletter_poll_minutes": "30",
    # Status:
    # Values for pipeline_last_status:
    # - "never"   : no completed runs yet
    # - "success" : last run completed without errors
    # - "error"   : last run encountered at least one error
    # - "running" : currently in progress (transient; also exposed via is_pipeline_running)
    "pipeline_last_status": "never",
    # Scraper status (for manual enrich jobs)
    "scrape_last_status": "never",
    # WordRank status (for manual/scheduled recomputes)
    "wordrank_last_status": "never",
    # Newsletter status
    "newsletter_last_status": "never",
    "newsletter_last_success_ts": "",
    "newsletter_last_error": "",
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
            color TEXT,
            kind  TEXT NOT NULL DEFAULT 'rss'
        );

        CREATE TABLE IF NOT EXISTS entries (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id       INTEGER NOT NULL,
            source_uid    TEXT,
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
        ("quality_score", "REAL DEFAULT 0.0"),
        ("assessment_label", "TEXT"),
        ("assessment_label_color", "TEXT"),
        ("viz_x", "REAL"),
        ("viz_y", "REAL"),
        ("og_title", "TEXT"),
        ("og_description", "TEXT"),
        ("og_image_url", "TEXT"),
        ("full_content", "TEXT"),
    ]:
        if col not in entry_cols:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {col} {definition}")

    feed_cols = {r[1] for r in conn.execute("PRAGMA table_info(feeds)").fetchall()}
    if "color" not in feed_cols:
        conn.execute("ALTER TABLE feeds ADD COLUMN color TEXT")
    if "kind" not in feed_cols:
        conn.execute("ALTER TABLE feeds ADD COLUMN kind TEXT NOT NULL DEFAULT 'rss'")
    entry_cols = {r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}
    if "source_uid" not in entry_cols:
        conn.execute("ALTER TABLE entries ADD COLUMN source_uid TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_feed_source_uid ON entries(feed_id, source_uid)"
    )

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
