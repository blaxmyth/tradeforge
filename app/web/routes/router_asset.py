from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import delete, text, func
import math
from sqlalchemy.exc import IntegrityError
from db.models import *
from db.database import *
from db.schemas import AssetSchema
from pydantic import TypeAdapter
from scripts.populate_assets import *
from scripts.populate_prices import *
from web.auth.auth import *
import pytz

ET = pytz.timezone("US/Eastern")

_TIMEFRAME_TABLE = {
    "1min":  ("asset_price",       "datetime"),
    "5min":  ("asset_price_5min",  "bucket"),
    "15min": ("asset_price_15min", "bucket"),
    "1hr":   ("asset_price_1hr",   "bucket"),
    "1day":  ("asset_price_1day",  "bucket"),
}

router = APIRouter(
    dependencies=[Depends(get_current_user_from_token)]
)

templates = Jinja2Templates(directory="/app/web/templates")

PAGE_SIZE = 50

@router.get("/assets")
async def assets(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_from_token), context: dict = Depends(get_authenticated_template_context)):

    asset_filter = request.query_params.get('filter', 'all')
    q = request.query_params.get('q', '').strip()
    page = max(1, int(request.query_params.get('page', 1)))
    offset = (page - 1) * PAGE_SIZE

    watchlist_ids = set(
        (await db.scalars(select(WatchList.asset_id).where(WatchList.user_id == current_user.id))).all()
    )

    if asset_filter == 'sp500':
        base = select(Asset).where(Asset.is_sp500 == True)
    elif asset_filter == 'crypto':
        base = select(Asset).where(Asset.asset_class == "crypto")
    elif asset_filter == 'watchlist':
        watchlist_base = (
            select(WatchList)
            .where(WatchList.user_id == current_user.id)
            .options(selectinload(WatchList.asset))
        )
        all_watchlist = (await db.scalars(watchlist_base)).all()
        raw_rows = [item.asset for item in all_watchlist if item.asset]
        if q:
            raw_rows = [a for a in raw_rows if q.lower() in a.symbol.lower() or q.lower() in (a.name or '').lower()]
        total = len(raw_rows)
        total_pages = math.ceil(total / PAGE_SIZE) if total else 1
        raw_rows = raw_rows[offset:offset + PAGE_SIZE]
        rows = [a.model_dump() for a in TypeAdapter(list[AssetSchema]).validate_python(raw_rows)]
        return templates.TemplateResponse("assets.html", {
            "request": request, "assets": rows, "selected": asset_filter,
            "watchlist_ids": watchlist_ids, "page": page, "total_pages": total_pages, "q": q,
            **context
        })
    else:
        base = select(Asset)

    if q:
        base = base.where(Asset.symbol.ilike(f'%{q}%') | Asset.name.ilike(f'%{q}%'))

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    total_pages = math.ceil(total / PAGE_SIZE) if total else 1

    result = await db.execute(base.order_by(Asset.symbol.asc()).limit(PAGE_SIZE).offset(offset))
    raw_rows = result.scalars().all()

    rows = [a.model_dump() for a in TypeAdapter(list[AssetSchema]).validate_python(raw_rows)]

    return templates.TemplateResponse("assets.html", {
        "request": request,
        "assets": rows,
        "selected": asset_filter,
        "watchlist_ids": watchlist_ids,
        "page": page,
        "total_pages": total_pages,
        "q": q,
        **context
    })

@router.get("/api/asset/{symbol}/bars")
async def get_bars(symbol: str, timeframe: str = "1min", limit: int = 300, db: AsyncSession = Depends(get_db)):
    if timeframe not in _TIMEFRAME_TABLE:
        return JSONResponse(status_code=400, content={"error": "invalid timeframe"})

    asset = await db.scalar(select(Asset).where(Asset.symbol == symbol))
    if not asset:
        return JSONResponse(status_code=404, content={"error": "asset not found"})

    table, time_col = _TIMEFRAME_TABLE[timeframe]

    result = await db.execute(
        text(f"""
            SELECT {time_col} AS t, open, high, low, close, volume
            FROM {table}
            WHERE asset_id = :asset_id
            ORDER BY {time_col} DESC
            LIMIT :limit
        """),
        {"asset_id": asset.id, "limit": limit},
    )
    rows = result.fetchall()

    bars = [
        {
            "time": int(ET.localize(row[0]).timestamp()),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": int(row[5]) if row[5] else 0,
        }
        for row in reversed(rows)
    ]

    return JSONResponse(content=bars)


@router.get("/asset/{symbol}")
async def asset_detail(request: Request, symbol, db: AsyncSession = Depends(get_db), context: dict = Depends(get_authenticated_template_context)):

    asset = await db.scalar(select(Asset).where(Asset.symbol == symbol))

    strategies_query = select(Strategy)
    strategies = (await db.scalars(strategies_query)).all()

    return templates.TemplateResponse("asset_detail.html", {"request": request, "asset": asset, "strategies": strategies, **context})

@router.get("/add_to_watchlist/{asset_id}")
async def add_to_watchlist(request: Request, asset_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_from_token)):

    try:
        db.add(WatchList(asset_id=asset_id, user_id=current_user.id))
        await db.commit()
    except IntegrityError:
        await db.rollback()

    return RedirectResponse(url="/assets?filter=watchlist", status_code=303)

@router.get("/delete_from_watchlist/{asset_id}")
async def delete_from_watchlist(request: Request, asset_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_from_token)):

    query = delete(WatchList).where(WatchList.asset_id == asset_id, WatchList.user_id == current_user.id)

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