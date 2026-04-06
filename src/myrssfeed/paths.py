from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
PROJECT_DIR = SRC_DIR.parent

DATA_DIR = PROJECT_DIR / "data"
WEB_DIR = PROJECT_DIR / "web"
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"
LOG_DIR = PROJECT_DIR / "logs"
FEEDS_DIR = PROJECT_DIR / "feeds"
BROWSER_PROFILE_DIR = PROJECT_DIR / "browser-profile"

DEFAULT_DB_FILE = FEEDS_DIR / "rss.db"
CATALOG_PATH = DATA_DIR / "feed_catalog.json"
