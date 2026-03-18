# myRSSfeed

Quick start:

```bash
git clone git@github.com:josephkaiser/myrssfeed.git
cd myrssfeed
bash install.sh
```

When `install.sh` finishes, use the browser URL it prints in the terminal. If your network supports mDNS, `http://myrssfeed.local:8080` should also work. The script also prints the LAN IP when it can detect one, and the logs endpoint is `http://<ip>:8080/api/logs`.

## Service Management

```bash
sudo systemctl status myrssfeed
sudo systemctl restart myrssfeed
sudo systemctl stop myrssfeed
sudo systemctl start myrssfeed
sudo journalctl -u myrssfeed -f
```

## Pages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main feed view |
| `GET` | `/article/{entry_id}` | Article detail page |
| `GET` | `/feeds` | My Feeds page |
| `GET` | `/discover` | Discover feeds page |
| `GET` | `/settings` | Settings page |
| `GET` | `/stats` | Stats dashboard |

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/feeds` | List subscribed feeds |
| `POST` | `/api/feeds` | Add a feed |
| `PATCH` | `/api/feeds/{feed_id}` | Update feed title or color |
| `DELETE` | `/api/feeds/{feed_id}` | Unsubscribe from a feed |
| `GET` | `/api/entries` | List entries with filters |
| `POST` | `/api/entries/{entry_id}/read` | Mark an entry as read |
| `POST` | `/api/entries/{entry_id}/like` | Toggle liked state |
| `POST` | `/api/entries/{entry_id}/vote` | Set liked state explicitly |
| `GET` | `/api/random-article` | Fetch one matching article |
| `GET` | `/api/settings` | Read settings |
| `POST` | `/api/settings` | Update settings |
| `POST` | `/api/refresh` | Start a full refresh |
| `GET` | `/api/refresh/status` | Refresh job status |
| `POST` | `/api/wordrank` | Run WordRank now |
| `GET` | `/api/wordrank/status` | WordRank status |
| `POST` | `/api/scrape` | Start scrape/enrichment |
| `GET` | `/api/scrape/status` | Scrape status |
| `POST` | `/api/newsletters/sync` | Start newsletter sync |
| `GET` | `/api/newsletters/status` | Newsletter sync status |
| `GET` | `/api/search` | Live search and suggestions |
| `POST` | `/api/discover/detect` | Detect feeds from a URL |
| `GET` | `/api/logs` | Recent log lines |
