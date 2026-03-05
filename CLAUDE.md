# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

myRSSfeed is a lightweight self-hosted RSS aggregator designed to run on a Raspberry Pi 5. It serves a local network at `https://myrssfeed.local`. No cloud APIs — everything runs on-device.

## Environments

**Dev PC (`euler`)** — where active development happens:
- Intel i7-11700K (16 threads), RTX 4090 (24 GB VRAM), 32 GB RAM, Ubuntu 24.04
- Use this to iterate quickly, validate LLM output quality, and benchmark approaches

**Production (Raspberry Pi 5)** — the deployment target:
- ARM64, CPU-only, ~8 GB RAM
- Scheduled jobs run unattended — latency doesn't matter, only correctness and memory safety do
- Daily pipeline runs at 06:00 and may take a few hours on Pi (acceptable)

**Design principle for LLM/ML features:** validate output quality on the dev PC first. If it produces good results there, the Pi will produce identical results — just slower.

## Running the app

```bash
source .venv/bin/activate
python main.py
```

App listens on port 8080. In production nginx proxies HTTPS → 8080.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Deploy to Pi:
```bash
rsync -av \
  --exclude='.venv/' \
  --exclude='feeds/' \
  --exclude='logs/' \
  --exclude='certs/' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  . pi@myrssfeed.local:/home/pi/myrssfeed/
ssh pi@myrssfeed.local 'sudo systemctl restart myrssfeed'
```

## Running scripts manually

```bash
python -m scripts.compile_feed    # fetch feeds + prune
python -m scripts.wordrank        # recompute scores
python -m scripts.visualization   # recompute 2D layout
python -m scripts.digest          # generate AI digest
```

## Architecture

**Request flow:** `nginx` → `uvicorn` (port 8080) → `FastAPI` (`main.py`) → `api/routes.py`

**Key modules:**
- `main.py` — entry point; configures logging (rotating file + stdout), initializes DB, starts scheduler
- `scheduler.py` — daily cron at 06:00: `run_pipeline()` = fetch → wordrank → visualization → digest. Also exported for use by `/api/refresh`.
- `api/routes.py` — all API endpoints and HTML page routes
- `api/schemas.py` — Pydantic models
- `utils/helpers.py` — `get_db()`, `init_db()` (creates all tables + runs migrations), `_migrate_db()`, `get_setting()`, `set_setting()`, `DEFAULTS`
- `scripts/compile_feed.py` — fetches feeds, upserts entries (with thumbnail extraction), prunes old entries
- `scripts/wordrank.py` — TF-IDF cosine similarity against liked articles → `entries.score`
- `scripts/visualization.py` — TF-IDF + SVD + t-SNE → `entries.viz_x/viz_y` + `viz_themes` table
- `scripts/digest.py` — extractive pre-filter + ollama HTTP → `daily_digests` table
- `web/templates/` — Jinja2 templates (`index.html`, `settings.html`, `viz.html`, `digest.html`)
- `web/static/` — `index.css`, `index.js`, `viz.js`, `settings.css`, `settings.js`

**Database:** SQLite at `feeds/rss.db`.

Tables: `feeds`, `entries`, `entries_fts` (FTS5), `settings`, `viz_themes`, `daily_digests`.

**Logging:** rotating file at `logs/myrssfeed.log` (10 MB × 5 backups) + stdout. Browser-accessible at `GET /api/logs?lines=100`.

## Key constraints

- **No ORM** — plain `sqlite3` with `conn.row_factory = sqlite3.Row`. Call `get_db()` directly.
- **scikit-learn imports are inside functions** — `wordrank.py` and `visualization.py` import sklearn inside `run_*()` to avoid slow startup of the web server.
- **digest.py uses stdlib only** — `urllib.request` for ollama HTTP calls, no extra deps.

## Settings

Stored in the `settings` table; defaults in `utils/helpers.py::DEFAULTS`:

| Key | Default | Notes |
|-----|---------|-------|
| `retention_days` | `"90"` | 0 = keep forever |
| `theme` | `"system"` | `"light"` / `"dark"` also valid |
| `ollama_url` | `"http://localhost:11434"` | |
| `ollama_model` | `"phi3:mini"` | Use `llama3.1:8b` for production quality |
| `digest_max_articles` | `"50"` | Top-N articles by score fed to LLM |

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Main feed UI |
| GET | `/viz` | Topic map page |
| GET | `/digest` | Digest page |
| GET | `/settings` | Settings page |
| GET/POST | `/api/feeds` | List / add feeds |
| DELETE | `/api/feeds/{id}` | Remove a feed |
| GET | `/api/entries` | Entries (`q`, `feed_id`, `limit`) |
| POST | `/api/entries/{id}/read` | Mark entry as read |
| POST | `/api/entries/{id}/like` | Toggle like (returns `{liked: bool}`) |
| GET | `/api/search` | Live search suggestions + previews |
| GET/POST | `/api/settings` | Read / write settings |
| POST | `/api/refresh` | Run full pipeline (fetch→rank→viz→digest) |
| GET | `/api/viz` | Viz data `{entries, themes}` |
| GET | `/api/digest` | Today's digest or 404 |
| GET | `/api/logs` | Recent log lines (`?lines=100`) |
