# myRSSfeed Design Document

A simple, self-hosted RSS aggregator for personal home use on a Raspberry Pi, accessible across the local network.


---

## Core principles

- Chronological feed by default, with personalized ranking layered on top
- No accounts, no algorithms forced on the user — just feeds, sorted for you
- All processing runs on-device; scheduled jobs can take hours if needed
- Goal: 1 month continuous uptime without reboot or crash; monthly maintenance (log rotation, cache clear) is acceptable

---

## Features

### Feed presentation
- Clicking an article opens it in a new tab; the article row changes color (read state) when returned to
- Inline images from article content where available (media:content, enclosures, og:image via feedparser)
- Feed favicons shown inline per article row using `https://www.google.com/s2/favicons?domain={domain}&sz=32`
- **Colored feed labels**: auto-assigned by hashing the category portion of the feed title (e.g. "US News" in "WSJ | US News") to a hue. Same category across sources → same hue, varied by source name for lightness/saturation. User can override per-feed color via a color picker in settings (stored in `feeds.color` column).

### Newsletter ingestion
- A dedicated IMAP mailbox can be configured in Settings and polled automatically
- Each unseen message is normalized into one `entries` row using a stable source UID, so repeat polls stay idempotent
- Newsletter bodies are sanitized before storage/rendering, and the article page prefers the cleaned full body when available

### Personalization (WordRank)
- Like button per article captures user preference
- WordRank model: TF-IDF vectors for all articles, cosine similarity to centroid of liked articles → score stored in `entries.score`
- Feed sorted by a blend of recency + score
- Recomputed during daily fetch (scikit-learn, no GPU needed — fast on Pi)

### Visualization
- A topic landscape view showing major themes across all feeds ("information diet" view)
- **Implementation**: TF-IDF on titles + summaries → truncated SVD (LSA, 50 dims) → t-SNE to 2D, fixed random seed for layout stability across days
- KMeans on the 50-dim space extracts top keywords per region to label major themes (e.g. "AI & LLMs", "Markets", "Ukraine")
- Each article is a dot, colored by feed; hover shows title; click opens article
- Density heatmap overlay (optional, nice-to-have)
- Recomputed daily with feed fetch; 2D coordinates stored in `entries` table

### Manual refresh
- A "Refresh now" button in the UI triggers the same full pipeline that runs at 06:00: feed fetch → prune → WordRank scoring → visualization recompute
- This allows fast iteration during development without waiting a full day
- The existing `/api/refresh` endpoint triggers the full pipeline, including newsletter ingestion

### Logging and observability
- **Server-side**: Python `logging` module with a rotating file handler (`logs/myrssfeed.log`), also emitted to stdout (captured by systemd/journalctl on Pi)
- **Browser-accessible**: `/api/logs` endpoint returns recent log lines (last N lines from the log file) so the user can inspect live behavior from any device on the LAN without SSH
- Log levels: INFO for normal operations (fetch started, N entries fetched, pipeline complete), WARNING for recoverable issues (feed timeout, parse error), ERROR for failures
- Goal: when the Pi misbehaves, the user can open `/api/logs` in the browser and share the output for debugging

---

## Scheduling (daily pipeline at 06:00)

```
06:00  compile_feed     — fetch all feeds, upsert entries, prune old entries
       newsletter       — poll IMAP, normalize unseen emails, store newsletter entries
       wordrank         — recompute TF-IDF scores for all entries vs liked articles
       visualization    — recompute 2D layout (fixed seed), store x/y in entries
```

Each stage logs start/end and item counts. If a stage fails, later stages are skipped and the error is logged.

---

## Database additions (planned, not yet implemented)

Beyond current tables (`feeds`, `entries`, `entries_fts`, `settings`):

| Column / Table | Purpose |
|----------------|---------|
| `entries.read` | Boolean, set when user clicks article |
| `entries.liked` | Boolean, set via like button |
| `entries.score` | Float, WordRank cosine similarity score |
| `entries.viz_x`, `entries.viz_y` | Float, 2D coordinates for visualization |
| `feeds.color` | Optional hex color override |
| `feeds.kind` | Distinguish the newsletter mailbox source from normal RSS feeds |
| `entries.source_uid` | Stable dedupe key for RSS links and newsletter message IDs |
| `newsletter_*` settings | IMAP host, port, username, password, folder, poll interval, and status |

---

## Tech decisions

| Concern | Decision |
|---------|----------|
| Favicons | Google favicon service (`s2/favicons`) — no local caching needed |
| Feed label colors | Auto-assign from category hash; user override via color picker |
| Viz layout stability | Fixed random seed in t-SNE/UMAP call |
| Viz recompute frequency | Daily with feed fetch |
| WordRank ML | scikit-learn TF-IDF + cosine similarity; no GPU, no sentence-transformers |
| Logging | Python rotating file handler + stdout; `/api/logs` browser endpoint |
| Uptime target | 1 month continuous; monthly maintenance window acceptable |
