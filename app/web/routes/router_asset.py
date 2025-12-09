from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import delete
from db.models import *
from db.database import *
from db.schemas import AssetSchema
from pydantic import TypeAdapter
from config import redis_client
from scripts.populate_assets import *
from scripts.populate_prices import *
from web.auth.auth import *
import json

router = APIRouter(
    dependencies=[Depends(get_current_user_from_token)]
)

templates = Jinja2Templates(directory="/app/web/templates")

@router.get("/assets")
async def assets(request: Request, asset_filter: str = "all", db: AsyncSession = Depends(get_db), context: dict = Depends(get_authenticated_template_context)):

    asset_filter = request.query_params.get('filter', False)

    cache_key = f"assets:{asset_filter}"
    
    cached_data = await redis_client.get(cache_key)

    if cached_data:
        rows = json.loads(cached_data)   
    
    if asset_filter == 'sp500':
        query = (
            select(Asset)
            .where(Asset.is_sp500 == True)
            .order_by(Asset.symbol.asc())
        )
        result = await db.execute(query)
        raw_rows = result.scalars().all()
        
    elif asset_filter == 'crypto':
        query = (
            select(Asset)
            .where(Asset.asset_class == "crypto")
            .order_by(Asset.symbol.asc())
        )
        result = await db.execute(query)
        raw_rows = result.scalars().all()

    elif asset_filter == 'watchlist':
        query = (
            select(WatchList)
            .options(selectinload(WatchList.asset))
        )
        watchlist_assets = (await db.scalars(query)).all()
        raw_rows = [item.asset for item in watchlist_assets]

    else:
        query = (
            select(Asset)
            .order_by(Asset.symbol.asc())
        )
        result = await db.execute(query)
        raw_rows = result.scalars().all()

    assets = TypeAdapter(list[AssetSchema]).validate_python(raw_rows)

    rows = [asset.model_dump() for asset in assets]

    await redis_client.setex(cache_key, 300, json.dumps(rows))  # Cache for 5 minutes

    return templates.TemplateResponse("assets.html", {
        "request": request,
        "assets": rows,
        "selected": asset_filter,
        **context
    })

@router.get("/asset/{symbol}")
async def asset_detail(request: Request, symbol, db: AsyncSession = Depends(get_db), context: dict = Depends(get_authenticated_template_context)):

    query = select(Asset).where(Asset.symbol == symbol)
    asset = await db.scalar(query)

    query = (
        select(AssetPrice)
        .where(AssetPrice.asset_id == asset.id)
        .order_by(AssetPrice.datetime.desc())
    )
    prices_result = await db.scalars(query)
    prices = prices_result.all()

    strategies_query = select(Strategy)
    strategies_result = await db.scalars(strategies_query)
    strategies = strategies_result.all()

    return templates.TemplateResponse("asset_detail.html", {"request": request, "asset": asset, "prices": prices, "strategies": strategies, **context})

@router.get("/add_to_watchlist/{asset_id}")
async def add_to_watchlist(request: Request, asset_id: int, db: AsyncSession = Depends(get_db)):

    asset = WatchList(asset_id=asset_id)

    db.add(asset)

    await db.commit()

    return RedirectResponse(url="/assets?filter=watchlist", status_code=303)

@router.get("/delete_from_watchlist/{asset_id}")
async def delete_from_watchlist(request: Request, asset_id: int, db: AsyncSession = Depends(get_db)):
    
    query = delete(WatchList).where(WatchList.asset_id == asset_id)

    await db.execute(query)

    await db.commit()

    return RedirectResponse(url="/assets?filter=watchlist", status_code=303)

@router.get("/populate_assets")
async def get_assets(request: Request, db: AsyncSession = Depends(get_db)):
    
    await populate_assets(db)

    return RedirectResponse(url="/assets", status_code=303)

@router.get("/populate_prices")
async def get_prices(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    
    background_tasks.add_task(populate_prices, db)

    return RedirectResponse(url="/assets", status_code=303)