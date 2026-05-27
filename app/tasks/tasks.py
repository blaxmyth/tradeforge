from celery import Celery
from celery.schedules import crontab
from scripts.populate_assets import populate_assets
from db.models import *
from db.database import *
import asyncio

redis = redis.Redis(host="redis", port=6379, decode_responses=True)

celery = Celery(
    "worker",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0",
)

celery.conf.timezone = "US/Eastern"

celery.conf.beat_schedule = {
    "run-populate-assets": {
        "task": "tasks.tasks.run_populate_assets",
        "schedule": crontab(minute=0, hour=23, day_of_week='1-5'),  
    }
}

@celery.task
def run_populate_assets():
    loop = asyncio.get_event_loop()

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(_run())

async def _run():
    async with async_session_maker() as session:
        await populate_assets(session)