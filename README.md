# myRSSfeed

A self-hosted RSS aggregator for your local network. Runs on a Raspberry Pi 5, fetches all your feeds daily at 6:00 AM, and serves a clean mobile-friendly web UI at **https://myrssfeed.local**.

---

## Features

- **Daily pipeline at 6:00 AM** — fetch feeds → rank articles → update topic map → generate digest
- **Manual refresh** button runs the same pipeline on demand
- **Personalized ranking** — like articles to train WordRank; similar articles are upranked automatically
- **Read state** — clicked articles dim so you can see what's new at a glance
- **Feed management** — add/remove RSS feeds from the browser
- **Filter by feed** or **search by keyword** across all articles
- **Inline images and favicons** — article thumbnails and feed icons shown in the feed
- **Colored feed labels** — auto-assigned by feed category name; override per-feed in settings
- **Topic Map** — 2D scatter plot of all articles by semantic similarity; hover to preview, click to open
- **AI Digest** — daily summary powered by ollama; runs locally on the Pi over ~4 hours
- **Live search** with word-completion suggestions
- **HTTPS via nginx** — TLS termination with a locally-trusted mkcert certificate
- **Accessible as `myrssfeed.local`** — mDNS via avahi, no DNS config needed
- **Logs viewer** — `https://myrssfeed.local/api/logs` shows recent server logs from any device on the LAN
- **No accounts, no cloud** — everything runs on-device; SQLite on a Pi 5

---

## Raspberry Pi install (production)

```bash
git clone <your-repo> ~/myrssfeed
cd ~/myrssfeed
bash install.sh
```

`install.sh` does everything in one shot:

1. Creates a Python virtualenv and installs all dependencies
2. Installs **ollama**, registers it as a systemd service, and pulls `phi3:mini`
3. Registers the app as a **systemd service** (binds to `127.0.0.1:8080`, starts after ollama)
4. Installs **nginx** and proxies HTTPS → uvicorn
5. Installs **mkcert**, generates a locally-trusted TLS certificate for `myrssfeed.local`
6. Sets the Pi's mDNS hostname via **avahi** so the `.local` name resolves on the LAN

Open on any device on the same Wi-Fi:

```
https://myrssfeed.local
```

### Adding devices (phones, laptops)

On each device, open a browser and go to:

```
http://myrssfeed.local/devices
```

The page works over plain HTTP before the certificate is trusted. Pick your OS and follow the instructions — one download and install, then `https://myrssfeed.local` works without warnings.

**Shortcuts:**
- **iPhone/iPad** — tap "Install profile" in Safari; iOS handles everything
- **Mac** — download and double-click `bootstrap.command` from the same page; it installs the cert automatically

### Managing the service

```bash
sudo systemctl status  myrssfeed
sudo systemctl restart myrssfeed
sudo systemctl reload  nginx
journalctl -u myrssfeed -f    # live logs
```

---

## Local development

```bash
bash start.sh
```

That's it. `start.sh` handles everything in one shot:
1. Creates `.venv` if it doesn't exist
2. Installs / syncs all Python dependencies
3. Starts ollama if it isn't already running (logs to `logs/ollama.log`)
4. Pulls `phi3:mini` if not already available
5. Starts the app at [http://localhost:8080](http://localhost:8080)

`feeds/rss.db` and `logs/myrssfeed.log` are created automatically on first run.
Press **Ctrl+C** to stop.

### Running pipeline stages manually

```bash
python -m scripts.compile_feed    # fetch feeds + prune old entries
python -m scripts.wordrank        # recompute article scores from likes
python -m scripts.visualization   # recompute topic map (t-SNE layout)
python -m scripts.digest          # generate AI digest via ollama
```

---

## Deploy to Pi (development workflow)

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

---

## Docker (with HTTPS)

Generate a cert first (requires [mkcert](https://github.com/FiloSottile/mkcert)):

```bash
mkcert -install
mkcert -cert-file certs/myrssfeed.local.pem \
       -key-file  certs/myrssfeed.local-key.pem \
       myrssfeed.local localhost 127.0.0.1
```

Then start everything:

```bash
docker compose up -d
```

- HTTP on port 80 redirects to HTTPS
- HTTPS on port 443 → nginx → uvicorn

The `feeds/` directory is volume-mounted so the database survives restarts.

---

## AI Digest (ollama)

The digest runs after the daily feed fetch. It uses a two-stage pipeline:
1. **Extractive pre-filter** — select the 2 most relevant sentences per article (no LLM)
2. **LLM summarize** — ollama generates a thematic digest from the extracts

**Model recommendations:**

| Use case | Model | Pi 5 speed (est.) |
|----------|-------|-------------------|
| Dev iteration | `phi3:mini` | ~18 tok/s |
| Production quality | `llama3.1:8b` | ~8 tok/s, ~2 hrs for 50 articles |

Configure model and ollama URL in **Settings → AI Digest**.

---

## Project layout

```
myrssfeed/
├── main.py                      # FastAPI app + logging setup + startup lifecycle
├── scheduler.py                 # APScheduler: daily pipeline at 6:00 AM
├── api/
│   ├── routes.py                # All API endpoints + HTML page routes
│   └── schemas.py               # Pydantic request/response models
├── scripts/
│   ├── compile_feed.py          # Fetch RSS feeds, extract thumbnails, prune entries
│   ├── wordrank.py              # TF-IDF personalization scoring
│   ├── visualization.py         # TF-IDF + SVD + t-SNE topic map
│   └── digest.py                # Extractive filter + ollama AI digest
├── utils/
│   └── helpers.py               # DB connection, schema init + migrations, settings
├── web/
│   ├── templates/
│   │   ├── index.html           # Main feed UI
│   │   ├── settings.html        # Settings page
│   │   ├── viz.html             # Topic map page
│   │   └── digest.html          # AI digest page
│   └── static/
│       ├── index.css / index.js
│       ├── viz.js               # Canvas scatter plot
│       ├── settings.css / settings.js
├── nginx/
│   ├── myrssfeed.conf           # nginx config (Pi / bare-metal)
│   └── nginx-docker.conf        # nginx config for Docker Compose
├── logs/                        # Rotating log files — gitignored
├── feeds/
│   └── rss.db                   # SQLite database — gitignored, auto-created
├── certs/                       # mkcert .pem files — gitignored
├── docker-compose.yml
├── Dockerfile
├── install.sh
└── requirements.txt
```

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main feed UI |
| `GET` | `/viz` | Topic map page |
| `GET` | `/digest` | AI digest page |
| `GET` | `/settings` | Settings page |
| `GET` | `/api/feeds` | List all feeds |
| `POST` | `/api/feeds` | Add a feed `{"url": "...", "title": "..."}` |
| `DELETE` | `/api/feeds/{id}` | Remove a feed and its articles |
| `GET` | `/api/entries` | List entries (`?q=`, `?feed_id=`, `?limit=`) |
| `POST` | `/api/entries/{id}/read` | Mark entry as read |
| `POST` | `/api/entries/{id}/like` | Toggle like on entry |
| `GET` | `/api/search` | Live search suggestions + previews (`?q=`) |
| `POST` | `/api/refresh` | Run full pipeline (fetch → rank → viz → digest) |
| `GET` | `/api/viz` | Visualization data `{entries, themes}` |
| `GET` | `/api/digest` | Today's digest or 404 |
| `GET` | `/api/logs` | Recent log lines (`?lines=100`) |
| `GET` | `/api/settings` | Get all settings |
| `POST` | `/api/settings` | Update settings |
