import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from . import jobs, runtime_settings
from .config import get_settings
from .db import init_db, session_scope
from .models import utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vibe_electricity")
logging.getLogger("httpx").setLevel(logging.WARNING)

scheduler = BackgroundScheduler(timezone="UTC")
JOB_ID = "sync"


def reschedule(minutes: int) -> None:
    job = scheduler.get_job(JOB_ID)
    if job:
        job.reschedule("interval", minutes=max(5, minutes))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as s:
        interval = runtime_settings.load(s).sync_interval_minutes
    first = utcnow() + timedelta(seconds=5) if get_settings().sync_on_startup else None
    scheduler.add_job(jobs.run_sync, "interval", minutes=max(5, interval), id=JOB_ID,
                      next_run_time=first, max_instances=1, coalesce=True)
    scheduler.start()
    log.info("scheduler started, Paperless sync every %d min", interval)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Vibe Electricity", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

from . import web  # noqa: E402  (routes need `app`)

app.include_router(web.router)
web.mount_static(app)
