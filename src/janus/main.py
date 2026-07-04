from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from janus.ingest.router import router
from janus.queue import worker
from janus.settings import settings
from janus.store.db import init_db
from janus.telegram import bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_prod()
    await init_db()
    await bot.start()
    tasks = [
        asyncio.create_task(worker.event_loop()),
        asyncio.create_task(worker.approvals_loop()),
        asyncio.create_task(worker.reminder_loop()),
    ]
    yield
    for task in tasks:
        task.cancel()
    await bot.stop()


app = FastAPI(title="janus", lifespan=lifespan)
app.include_router(router)
