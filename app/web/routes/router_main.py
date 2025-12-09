from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from web.auth.auth import *
from config import redis_client

router = APIRouter()

templates = Jinja2Templates(directory="/app/web/templates")

@router.get("/", response_class=HTMLResponse)
async def index(context: dict = Depends(get_authenticated_template_context)):

    return templates.TemplateResponse("index.html", context)

@router.get("/ping-redis")
async def ping_redis():
    ping = await redis_client.ping()
    return {"ping": ping}