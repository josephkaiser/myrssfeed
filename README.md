# myRSSfeed

A simple, self-hosted RSS aggregator for your local network. Runs on a Raspberry Pi, fetches all your feeds once daily at 9:00 AM, and presents them in a clean mobile-friendly web UI accessible at **https://myrssfeed.local** from any device on the same network.

---

## Features

- **Daily fetch at 9:00 AM** via APScheduler (local time, no cron setup needed)
- **Manual refresh** button for immediate updates
- **Feed management** — add/remove RSS feeds directly from the browser
- **Filter by feed** or **search by keyword** across all articles
- **Topics view** — articles automatically clustered by semantic similarity using `sentence-transformers` + K-Means; browse by topic card
- **Today's Digest** — one headline per topic cluster for a quick overview of the day's news
- **AI Digest** — optional LLM-generated prose bullet summary via a local [ollama](https://ollama.com) instance (no cloud, no API key)
- **HTTPS via nginx** — TLS termination with a locally-trusted mkcert certificate
- **Accessible as `myrssfeed.local`** — mDNS hostname via avahi, no DNS config needed
- **No accounts, no algorithms** — just your feeds, sorted newest-first
- **Lightweight** — SQLite, runs comfortably on a Raspberry Pi 4

---

## Raspberry Pi install (production)

```bash
git clone <your-repo> ~/myrssfeed
cd ~/myrssfeed
bash install.sh
```

`install.sh` does everything in one shot:

1. Creates a Python virtualenv and installs Python dependencies
2. Registers the app as a **systemd service** (binds to `127.0.0.1:8080`)
3. Installs **nginx** and proxies HTTPS → uvicorn
4. Installs **mkcert**, generates a locally-trusted TLS certificate for `myrssfeed.local`
5. Sets the Pi's mDNS hostname via **avahi** so the `.local` name resolves on the LAN

After install, open on any device on the same Wi-Fi:

```
https://myrssfeed.local
```

### Trusting the certificate on each device

mkcert creates a private Certificate Authority that is automatically trusted on the Pi. Install the same CA on any other device (phone, laptop) that will access the feed.

```bash
# On the Pi — find the CA file
mkcert -CAROOT   # prints something like /home/pi/.local/share/mkcert
```

Copy `rootCA.pem` to each device and install it:

| Device | Steps |
|--------|-------|
| **iOS** | AirDrop or email the file → Settings → tap the profile → trust it |
| **Android** | Settings → Security → Install from storage |
| **macOS** | Double-click → Keychain Access → set trust to "Always Trust" for SSL |
| **Windows** | Double-click → Install Certificate → Trusted Root Certification Authorities |

### Managing the services

```bash
sudo systemctl status  myrssfeed
sudo systemctl restart myrssfeed
sudo systemctl reload  nginx
journalctl -u myrssfeed -f    # live logs
```

---

## Optional: AI Digest with ollama

The **Today's Digest** view can generate a prose bullet summary of the day's news using a local LLM — no cloud calls, no API key.

### 1. Install ollama on the Pi

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Pull a model

`llama3.2:1b` is recommended for the Pi 4 — fast inference, ~1 GB download:

```bash
ollama pull llama3.2:1b
```

Other options (heavier but higher quality):

```bash
ollama pull phi3:mini        # ~2 GB, good quality
ollama pull mistral:7b-q4   # ~4 GB, best quality, slower on Pi
```

### 3. Configure in Settings

Open **https://myrssfeed.local/settings** and set:

- **ollama URL** — `http://localhost:11434` (default, if ollama is on the same Pi)
- **ollama model** — `llama3.2:1b` (or whichever model you pulled)

Then go to **Today's Digest** and click **Generate**. The first run takes 30–90 seconds on a Pi 4 with a 1B model; the result is cached and returned instantly on subsequent loads.

> **Note:** The digest caches one result per calendar day. Use the **regenerate** link in the digest to force a fresh summary.

---

## Topics clustering

After fetching feeds, the app can cluster articles by semantic similarity and let you browse by topic. The pipeline runs automatically after the daily fetch. You can also trigger it manually:

1. Go to **Settings → Re-cluster topics**
2. A progress bar tracks the pipeline stages: Loading model → Encoding → Clustering → Labelling → Saving

**Settings:**
- **Number of topic clusters** — how many K-Means groups to create (default: 10; range: 2–100)

The clustering uses [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) (~80 MB, CPU-only) and scikit-learn. First run will download the model to the Pi.

---

## Local development (Mac / Linux)

```bash
cd myrssfeed
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Open [http://localhost:8080](http://localhost:8080) — no nginx needed during dev.

To use the AI Digest locally, install ollama on your machine and point Settings to `http://localhost:11434`.

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
- HTTPS on port 443 → nginx → uvicorn app

The `feeds/` directory is volume-mounted so the SQLite database survives container restarts.

> **ollama with Docker:** ollama is not included in the Docker image. Point the ollama URL setting to `http://host-gateway:11434` (or your Pi's LAN IP) if you run ollama on the host.

---

## Project layout

```
myrssfeed/
├── main.py                    # FastAPI app + startup lifecycle
├── scheduler.py               # APScheduler: daily 9 AM feed fetch + re-cluster
├── api/
│   ├── routes.py              # REST endpoints + HTML UI routes
│   └── schemas.py             # Pydantic request/response models
├── scripts/
│   ├── compile_feed.py        # Fetches RSS feeds, stores entries in SQLite
│   └── cluster_topics.py      # sentence-transformers + K-Means topic clustering
├── utils/
│   └── helpers.py             # DB connection, schema init, settings helpers
├── web/
│   └── templates/
│       ├── index.html         # Main UI (feeds, topics, digest views)
│       └── settings.html      # Settings page
├── nginx/
│   ├── myrssfeed.conf         # nginx site config (Pi / bare-metal)
│   └── nginx-docker.conf      # nginx config for Docker Compose
├── certs/                     # Mount mkcert .pem files here (gitignored)
├── feeds/
│   └── rss.db                 # SQLite database (auto-created on first run)
├── docker-compose.yml
├── Dockerfile
├── install.sh
└── requirements.txt
```

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/settings` | Settings page |
| `GET` | `/api/feeds` | List all feeds |
| `POST` | `/api/feeds` | Add a feed `{"url": "...", "title": "..."}` |
| `DELETE` | `/api/feeds/{id}` | Remove a feed and its articles |
| `GET` | `/api/entries` | List entries (`?q=`, `?feed_id=`, `?limit=`) |
| `POST` | `/api/refresh` | Manually trigger a feed fetch |
| `GET` | `/api/topics` | List topic clusters with article counts |
| `GET` | `/api/topics/{id}/entries` | Articles in a topic cluster (`?limit=`, `?offset=`) |
| `POST` | `/api/recluster` | Re-run the topic clustering pipeline |
| `GET` | `/api/recluster/status` | Poll the progress of the most recent clustering job |
| `GET` | `/api/settings` | Get all settings |
| `POST` | `/api/settings` | Update settings |
| `GET` | `/api/digest` | Cluster-based bullet digest for a date (`?date=YYYY-MM-DD`) |
| `POST` | `/api/digest/llm` | Generate (or return cached) AI prose digest via ollama (`?date=YYYY-MM-DD`) |
| `DELETE` | `/api/digest/llm` | Clear the cached AI digest for a date (`?date=YYYY-MM-DD`) |
