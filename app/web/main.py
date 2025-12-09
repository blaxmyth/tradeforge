from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException as StarletteHTTPException
from web.routes.base import router
from contextlib import asynccontextmanager
from db.models import *
from db.database import *
from prom.metrics import router as metrics_router, prometheus_middleware
from web.auth.auth import unauthorized_exception_handler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run startup logic
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(lifespan=lifespan)

app.add_exception_handler(StarletteHTTPException, unauthorized_exception_handler)

app.include_router(router)
app.include_router(metrics_router)

app.mount("/static", StaticFiles(directory="/app/web/static"), name="static")

app.middleware("http")(prometheus_middleware)
