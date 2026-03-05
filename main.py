import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.jobs import job_queue
from app.routes.document import router as document_router
from app.routes.pages import router as pages_router
from app.routes.upload import router as upload_router

logging.basicConfig(
    level=logging.DEBUG if os.getenv("LOG_LEVEL", "").upper() == "DEBUG" else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(job_queue.worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="scanme", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(pages_router)
app.include_router(upload_router)
app.include_router(document_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
