# myRSSfeed

myRSSfeed is a self-hosted RSS reader built with FastAPI + SQLite, designed to run well on a Raspberry Pi and be reachable on your local network.

## Current capabilities

- Subscribe/unsubscribe feeds and manage feed metadata (title, color).
- Discover feeds from a curated catalog and detect RSS/Atom links from a URL.
- Read entries with filters (query, date range, quality level, scope, themes, sort).
- Mark articles read, like/unlike entries, and open article detail pages.
- Trigger background refreshes and check refresh status.
- Run WordRank and view WordRank status.
- Optional newsletter ingestion via IMAP (toggle in settings).
- View service logs through the built-in logs endpoint.

## Install

### Raspberry Pi / Debian (recommended)

This sets up a virtual environment, installs dependencies, and configures a `systemd` service (`myrssfeed`) on port `8080`.

```bash
git clone git@github.com:josephkaiser/myrssfeed.git
cd myrssfeed
bash install.sh
```

After install, open the URL printed by the script. If mDNS is available, this often works:

- `http://myrssfeed.local:8080`

Logs endpoint:

- `http://<host>:8080/api/logs`

### Local/manual run (any OS)

```bash
git clone git@github.com:josephkaiser/myrssfeed.git
cd myrssfeed
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Default app URL:

- `http://localhost:8080`

## Service management (Linux/systemd)

```bash
sudo systemctl status myrssfeed
sudo systemctl restart myrssfeed
sudo systemctl stop myrssfeed
sudo systemctl start myrssfeed
sudo journalctl -u myrssfeed -f
```

## Web pages

- `/` main feed view
- `/article/{entry_id}` article details
- `/feeds` subscribed feeds
- `/discover` discover/catalog page
- `/add-feed` add-feed helper page
- `/settings` runtime settings
- `/stats` stats dashboard

## API (most used)

- `GET /api/feeds` list subscribed feeds
- `POST /api/feeds` add a feed
- `DELETE /api/feeds/{feed_id}` unsubscribe a feed
- `GET /api/entries` list entries with filters/pagination
- `POST /api/entries/{entry_id}/read` mark read
- `POST /api/entries/{entry_id}/like` toggle like
- `GET /api/random-article` open a random matching article
- `POST /api/refresh` trigger background refresh
- `GET /api/refresh/status` check refresh status
- `GET /api/settings` and `POST /api/settings` read/update settings
- `POST /api/discover/detect` detect RSS/Atom from a URL
- `GET /api/logs` view recent logs

For implementation details, see `main.py` for the full route list.
