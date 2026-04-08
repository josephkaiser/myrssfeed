import logging
import logging.handlers
import os
import sqlite3
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from myrssfeed.paths import LOG_DIR, STATIC_DIR, TEMPLATES_DIR
from myrssfeed.routes.entries_api import EntryAPIRoutes
from myrssfeed.routes.feeds_api import FeedAPIRoutes
from myrssfeed.routes.system_api import SystemAPIRoutes
from myrssfeed.routes.ui import UIRoutes
from myrssfeed.scripts.newsletter_ingest import is_newsletter_running, run_newsletter_ingest_async
from myrssfeed.scripts.scheduler import (
    create_scheduler,
    get_pipeline_progress,
    is_pipeline_running,
    reconfigure_scheduler,
    run_pipeline_async,
    trigger_pipeline_refresh_if_due_on_startup,
)
from myrssfeed.services.catalog import (
    FEED_CATALOG,
    STARTER_CATALOG_URLS,
    STATIC_CATALOG_URLS,
    seed_catalogue_feeds,
    seed_starter_subscriptions,
)
from myrssfeed.utils.helpers import (
    DEFAULTS as CORE_DEFAULTS,
    DB_FILE as CORE_DB_FILE,
    get_db as core_get_db,
    get_setting as core_get_setting,
    init_db as core_init_db,
    set_setting as core_set_setting,
)
import myrssfeed.utils.helpers as core_helpers


os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = str(LOG_DIR / "myrssfeed.log")


def _configure_logging() -> logging.Logger:
    formatter = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s - %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not any(getattr(handler, "name", "") == "myrssfeed-stream" for handler in root.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.name = "myrssfeed-stream"
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if not any(getattr(handler, "name", "") == "myrssfeed-file" for handler in root.handlers):
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        file_handler.name = "myrssfeed-file"
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return logging.getLogger(__name__)


logger = _configure_logging()


DEFAULTS: dict[str, str] = CORE_DEFAULTS
DB_FILE: str = CORE_DB_FILE
_FEED_CATALOG = FEED_CATALOG
_STARTER_CATALOG_URLS = STARTER_CATALOG_URLS
_STATIC_CATALOG_URLS = STATIC_CATALOG_URLS


def _sync_db_file() -> None:
    core_helpers.DB_FILE = DB_FILE


def get_db() -> sqlite3.Connection:
    _sync_db_file()
    return core_get_db()


def init_db() -> None:
    _sync_db_file()
    core_init_db()
    conn = get_db()
    try:
        seed_catalogue_feeds(conn)
        seed_starter_subscriptions(conn)
    finally:
        conn.close()


def get_setting(key: str) -> str:
    _sync_db_file()
    return core_get_setting(key)


def set_setting(key: str, value: str) -> None:
    _sync_db_file()
    core_set_setting(key, value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    try:
        if trigger_pipeline_refresh_if_due_on_startup():
            logger.info("Startup: pipeline refresh was due (refresh window exceeded).")
    except Exception:
        logger.exception("Startup: refresh due-check failed.")
    logger.info("myRSSfeed started.")
    yield
    scheduler.shutdown(wait=False)
    logger.info("myRSSfeed stopped.")


app = FastAPI(title="myRSSfeed", lifespan=lifespan)

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


ui_routes = UIRoutes(
    templates=templates,
    get_db=get_db,
    get_setting=get_setting,
    set_setting=set_setting,
    defaults=DEFAULTS,
    logger=logger,
)
feed_api_routes = FeedAPIRoutes(
    get_db=get_db,
    is_pipeline_running=is_pipeline_running,
)
entry_api_routes = EntryAPIRoutes(get_db=get_db)
system_api_routes = SystemAPIRoutes(
    get_db=get_db,
    get_setting=get_setting,
    set_setting=set_setting,
    defaults=DEFAULTS,
    reconfigure_scheduler=reconfigure_scheduler,
    is_pipeline_running=is_pipeline_running,
    run_pipeline_async=run_pipeline_async,
    get_pipeline_progress=get_pipeline_progress,
    is_newsletter_running=is_newsletter_running,
    run_newsletter_ingest_async=run_newsletter_ingest_async,
    logger=logger,
    log_file=LOG_FILE,
)

ui_routes.register(app)
feed_api_routes.register(app)
entry_api_routes.register(app)
system_api_routes.register(app)


index = ui_routes.index
article_page = ui_routes.article_page
feeds_page = ui_routes.feeds_page
add_feed_page = ui_routes.add_feed_page
discover_page = ui_routes.discover_page
settings_page = ui_routes.settings_page
stats_page = ui_routes.stats_page

list_feeds = feed_api_routes.list_feeds
add_feed = feed_api_routes.add_feed
update_feed = feed_api_routes.update_feed
delete_feed = feed_api_routes.delete_feed
subscribe_feed = feed_api_routes.subscribe_feed
remove_feed_from_service = feed_api_routes.remove_feed_from_service
remove_from_catalog = feed_api_routes.remove_from_catalog

list_entries = entry_api_routes.list_entries
mark_read = entry_api_routes.mark_read
toggle_like = entry_api_routes.toggle_like
set_like = entry_api_routes.set_like

get_settings = system_api_routes.get_settings
update_settings = system_api_routes.update_settings
trigger_refresh = system_api_routes.trigger_refresh
get_refresh_status = system_api_routes.get_refresh_status
live_search = system_api_routes.live_search
detect_feeds = system_api_routes.detect_feeds
trigger_newsletter_sync = system_api_routes.trigger_newsletter_sync
get_newsletter_status = system_api_routes.get_newsletter_status
run_wordrank_now = system_api_routes.run_wordrank_now
get_wordrank_status = system_api_routes.get_wordrank_status
get_logs = system_api_routes.get_logs


def main() -> None:
    host = os.environ.get("MYRSSFEED_SERVER_HOST", "0.0.0.0")
    port_raw = os.environ.get("MYRSSFEED_SERVER_PORT", "8080")
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 8080
    uvicorn.run("myrssfeed.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
