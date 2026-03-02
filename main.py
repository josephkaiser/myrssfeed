import logging
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from utils.helpers import init_db
from scheduler import create_scheduler
from api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
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
