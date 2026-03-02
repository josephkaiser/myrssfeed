# myRSSfeed: A simple and lightweight self-hosted RSS feed for personal home use
Runs on a raspberry pi computer and works across a local network
No intermediaries, just the necessary plumbing for creating a feed
No algorithms, you can sort your feed as you please


### File directory overview
rss_aggregator_app/
├── main.py               # Starts API server & scheduler
├── scheduler.py          # Handles daily task scheduling
├── api/
│   ├── __init__.py
│   ├── routes.py         # REST endpoints for feed management
│   └── schemas.py        # Pydantic models for API
├── web/
│   ├── templates/        # Optional: HTML pages for UI
│   └── static/           # CSS/JS if needed
├── feeds/
│   └── feeds.json        # Persisted list of RSS feed URLs
├── scripts/
│   └── compile_feed.py   # Logic to fetch and merge RSS feeds
├── utils/
│   └── helpers.py
├── requirements.txt
├── Dockerfile
├── install.sh            # Optional: sets up system service
└── create-deb-file.sh    # Optional: packages app for Debian

### Database Schema Example (SQLite)

```sql
CREATE TABLE feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    title TEXT
);

CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER,
    title TEXT,
    link TEXT,
    published DATETIME,
    summary TEXT,
    UNIQUE(feed_id, link),
    FOREIGN KEY(feed_id) REFERENCES feeds(id)
);

-- Optional: Full-text search
CREATE VIRTUAL TABLE entries_fts USING fts5(title, summary, content='entries', content_rowid='id');
```

AGENT PROMPT
We have an existing rss feed web app that runs on a raspberry pi as backend and serves a local nginx server to myrssfeed.local. 

The feed is currently organized chronologically or can be searched or use the feed labels to subgroup. 

We need to think of some ideas to present the feed more topically across the separate feeds.

How can we modify the feed to be more engaging to the user? Can we group articles of seemingly similar topics?

Can we use a simple LLM model trained on the words in our database to group into similarity clusters and present a graphical way to navigate for user?

---

## Suggested Agent Prompt — Topical Feed Organizer

Use the following prompt when engaging a coding agent (e.g. Cursor, Claude, GPT-4) to implement this feature end-to-end:

---

> **Context**
> I have a self-hosted RSS aggregator called myRSSfeed. It runs on a Raspberry Pi as a FastAPI/uvicorn app behind nginx. The database is SQLite (`feeds/rss.db`). The schema has two main tables:
> - `feeds(id, url, title)` — the subscribed RSS sources
> - `entries(id, feed_id, title, link, published, summary)` — individual articles, with an FTS5 virtual table `entries_fts` over `title` and `summary`
>
> The frontend is a single Jinja2 template (`web/templates/index.html`) served by FastAPI. The app must remain lightweight — no GPU, no cloud APIs, no heavy external services — because it runs on a Raspberry Pi 4 (4 GB RAM).
>
> **Goal**
> Add a "Topics" view that clusters articles by semantic similarity and lets the user browse by topic cluster rather than by feed or chronological order. This should feel like a navigable topic map, not just a flat list.
>
> **Specific tasks**
>
> 1. **Embedding + clustering pipeline** (`scripts/cluster_topics.py`)
>    - Use `sentence-transformers` with the `all-MiniLM-L6-v2` model (fast, ~80 MB, CPU-friendly) to generate embeddings from each entry's `title + " " + summary` text.
>    - Run K-Means (scikit-learn) over the embeddings. Start with k=10 clusters; make k a configurable setting stored in the `settings` table via the existing `set_setting` / `get_setting` helpers in `utils/helpers.py`.
>    - Derive a human-readable label for each cluster by extracting the top-5 TF-IDF terms across all articles in that cluster (use `sklearn.feature_extraction.text.TfidfVectorizer`).
>    - Persist results in two new SQLite tables:
>      - `topic_clusters(id INTEGER PRIMARY KEY, label TEXT, centroid BLOB)` — centroid stored as a numpy array serialised with `numpy.tobytes()`.
>      - `entry_topics(entry_id INTEGER, cluster_id INTEGER, score REAL)` — cosine similarity of the entry embedding to its assigned centroid.
>    - Re-run this script automatically after each daily feed fetch by calling it from `scheduler.py` (after `compile_feed.py` finishes).
>    - Add `"topic_clusters"` and `"num_topic_clusters"` (default `"10"`) to the `DEFAULTS` dict in `utils/helpers.py` and create the new tables in `init_db()`.
>
> 2. **API endpoint** (`api/routes.py` + `api/schemas.py`)
>    - Add `GET /api/topics` — returns a list of `{id, label, article_count}` objects sorted by `article_count DESC`.
>    - Add `GET /api/topics/{cluster_id}/entries` — returns paginated `EntryOut` objects for that cluster, ordered by `score DESC` then `published DESC`. Reuse the existing `EntryOut` Pydantic model; add optional `cluster_id: Optional[int]` and `score: Optional[float]` fields to it.
>    - Wire both routes into the existing `api_router` in `api/routes.py`.
>
> 3. **Frontend "Topics" view** (`web/templates/index.html`)
>    - Add a **Topics** tab alongside the existing feed-filter bar. Clicking it switches the main content area into topics mode without a page reload (vanilla JS, no framework).
>    - In topics mode, render a **bubble/card grid**: one card per cluster showing the cluster label and article count. Cards should use the existing dark-theme CSS variables already in the template.
>    - Clicking a card fetches `/api/topics/{id}/entries` and renders the articles in the same article-card style used elsewhere in the template.
>    - A **"Back to topics"** breadcrumb link returns to the full cluster grid.
>    - No external JS libraries — keep it vanilla to stay consistent with the rest of the template.
>
> 4. **Dependencies** (`requirements.txt`)
>    - Add `sentence-transformers`, `scikit-learn`, and `numpy` (pin to versions compatible with Python 3.11 on ARM64/Raspberry Pi OS Bookworm).
>    - Do not add any GPU-specific packages.
>
> 5. **Manual re-cluster button**
>    - Add a `POST /api/recluster` endpoint that triggers `scripts/cluster_topics.py` synchronously (like the existing `/api/refresh` triggers `compile_feed.py`).
>    - Expose it as a small "Re-cluster topics" button in the settings panel (`web/templates/settings.html`) next to the existing manual refresh button.
>
> **Constraints**
> - All new code must follow the existing patterns: plain `sqlite3` (no ORM), FastAPI dependency injection via `Depends(get_db)` is not yet used — just call `get_db()` directly as the existing routes do.
> - Keep the clustering fully offline — no calls to OpenAI or any remote embedding API.
> - The clustering script should be idempotent: running it twice produces the same cluster table state (delete + re-insert, don't append).
> - Preserve all existing routes and UI behaviour; the Topics tab is purely additive.

---

The clustering needs a progress bar to see how much longer to go. And should be able to be run within feeds as well as across entire feed-base

Is it possible to make an LLM create a bulletpoint highlighted list summarizing the main stories of the day? In a way that groups the similar stories together to be summarized in one neutral bullet. And uses as many bullets as needed to cover all the stories but does not repeat. And prioritizes stories appropriately. How would we best appraoch making this sort of feed?