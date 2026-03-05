import logging
import logging.handlers
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from utils.helpers import init_db
from scheduler import create_scheduler
from api.routes import router

_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(_LOG_DIR, "myrssfeed.log")

_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
_root = logging.getLogger()
_root.setLevel(logging.INFO)

_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)

_fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5)
_fh.setFormatter(_fmt)
_root.addHandler(_fh)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("myRSSfeed started.")
    yield
    scheduler.shutdown(wait=False)
    logger.info("myRSSfeed stopped.")


app = FastAPI(title="myRSSfeed", lifespan=lifespan)

_static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
