from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import delete, text, func
import math
import pandas as pd
from datetime import timezone
from sqlalchemy.exc import IntegrityError
from db.models import *
from db.database import *
from db.schemas import AssetSchema
from pydantic import TypeAdapter
from scripts.populate_assets import *
from scripts.populate_prices import *
from web.auth.auth import *

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
            "time": int(row[0].replace(tzinfo=timezone.utc).timestamp()),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": int(row[5]) if row[5] else 0,
        }
        for row in reversed(rows)
    ]

    return JSONResponse(content=bars)


@router.get("/api/asset/{symbol}/indicators")
async def get_indicators(symbol: str, timeframe: str = "1min", ema: str = "200", db: AsyncSession = Depends(get_db)):
    if timeframe not in _TIMEFRAME_TABLE:
        return JSONResponse(status_code=400, content={"error": "invalid timeframe"})

    asset = await db.scalar(select(Asset).where(Asset.symbol == symbol))
    if not asset:
        return JSONResponse(status_code=404, content={"error": "asset not found"})

    # Parse and validate requested EMA periods
    ema_periods = []
    for p in ema.split(","):
        try:
            n = int(p.strip())
            if 2 <= n <= 500:
                ema_periods.append(n)
        except ValueError:
            pass
    if not ema_periods:
        ema_periods = [9, 20, 50]
    ema_periods = ema_periods[:10]  # cap at 10

    table, time_col = _TIMEFRAME_TABLE[timeframe]

    result = await db.execute(
        text(f"""
            SELECT {time_col} AS t, high, low, close
            FROM {table}
            WHERE asset_id = :asset_id
            ORDER BY {time_col} DESC
            LIMIT 500
        """),
        {"asset_id": asset.id},
    )
    rows = result.fetchall()
    if len(rows) < 2:
        return JSONResponse(content={})
    rows = list(reversed(rows))

    df = pd.DataFrame(rows, columns=["t", "high", "low", "close"])
    close = df["close"].astype(float)
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)

    # EMAs — compute only the requested periods
    for period in ema_periods:
        df[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()

    # Bollinger Bands (SMA ± 2σ over 20 bars)
    bb_mid        = close.rolling(20).mean()
    bb_std        = close.rolling(20).std()
    df["bb_upper"]  = bb_mid + 2 * bb_std
    df["bb_middle"] = bb_mid
    df["bb_lower"]  = bb_mid - 2 * bb_std

    # RSI (Wilder EMA, length=14)
    delta    = close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    avg_loss = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    macd_line     = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal   = macd_line.ewm(span=9, adjust=False).mean()
    df["macd"]        = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"]   = macd_line - macd_signal

    # Stochastic (14, 3, 3)
    denom        = (high.rolling(14).max() - low.rolling(14).min()).replace(0, float("nan"))
    fast_k       = 100 * (close - low.rolling(14).min()) / denom
    df["stoch_k"] = fast_k.rolling(3).mean()
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    # ADX (14) with Wilder EMA
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    dm_plus_raw  = high.diff()
    dm_minus_raw = -low.diff()
    dm_plus  = dm_plus_raw.where((dm_plus_raw  > dm_minus_raw) & (dm_plus_raw  > 0), 0.0)
    dm_minus = dm_minus_raw.where((dm_minus_raw > dm_plus_raw)  & (dm_minus_raw > 0), 0.0)
    atr14    = tr.ewm(alpha=1/14, adjust=False).mean()
    di_plus  = 100 * dm_plus.ewm(alpha=1/14,  adjust=False).mean() / atr14
    di_minus = 100 * dm_minus.ewm(alpha=1/14, adjust=False).mean() / atr14
    di_sum   = (di_plus + di_minus).replace(0, float("nan"))
    dx       = 100 * (di_plus - di_minus).abs() / di_sum
    df["adx"]     = dx.ewm(alpha=1/14, adjust=False).mean()
    df["adx_pos"] = di_plus
    df["adx_neg"] = di_minus

    df = df.tail(300)

    def to_series(col):
        out = []
        for row in df.itertuples(index=False):
            v = getattr(row, col)
            if not pd.isna(v):
                out.append({"time": int(row.t.replace(tzinfo=timezone.utc).timestamp()), "value": round(float(v), 4)})
        return out

    hist = []
    for row in df.itertuples(index=False):
        v = row.macd_hist
        if not pd.isna(v):
            fv = float(v)
            hist.append({"time": int(row.t.replace(tzinfo=timezone.utc).timestamp()), "value": round(fv, 4),
                         "color": "#26a69a" if fv >= 0 else "#ef5350"})

    ema_out = {f"ema_{p}": to_series(f"ema_{p}") for p in ema_periods}

    return JSONResponse(content={
        **ema_out,
        "bb_upper":    to_series("bb_upper"),
        "bb_middle":   to_series("bb_middle"),
        "bb_lower":    to_series("bb_lower"),
        "rsi":         to_series("rsi"),
        "macd":        to_series("macd"),
        "macd_signal": to_series("macd_signal"),
        "macd_hist":   hist,
        "stoch_k":     to_series("stoch_k"),
        "stoch_d":     to_series("stoch_d"),
        "adx":         to_series("adx"),
        "adx_pos":     to_series("adx_pos"),
        "adx_neg":     to_series("adx_neg"),
    })


@router.get("/api/asset/{symbol}/signals")
async def get_signals(symbol: str, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(SignalLog.fired_at, SignalLog.direction, SignalLog.entry_time)
        .where(SignalLog.symbol == symbol)
        .order_by(SignalLog.fired_at.asc())
    )).fetchall()

    results = []
    for row in rows:
        if not row.fired_at:
            continue
        # Place the marker on the actual signal candle, not when Celery detected it
        bar_dt = row.fired_at
        if row.entry_time:
            try:
                h, m = row.entry_time.split(":")
                bar_dt = row.fired_at.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            except (ValueError, AttributeError):
                pass
        results.append({
            "time":      int(bar_dt.replace(tzinfo=timezone.utc).timestamp()),
            "direction": row.direction,
        })

    return JSONResponse(content=results)


@router.get("/asset/{symbol}")
async def asset_detail(request: Request, symbol, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_from_token), context: dict = Depends(get_authenticated_template_context)):

    asset = await db.scalar(select(Asset).where(Asset.symbol == symbol))

    strategies = (await db.scalars(select(Strategy))).all()

    on_watchlist = await db.scalar(
        select(WatchList.asset_id)
        .where(WatchList.asset_id == asset.id, WatchList.user_id == current_user.id)
    ) is not None

    return templates.TemplateResponse("asset_detail.html", {"request": request, "asset": asset, "strategies": strategies, "on_watchlist": on_watchlist, **context})

@router.get("/add_to_watchlist/{asset_id}")
async def add_to_watchlist(request: Request, asset_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_from_token)):

    try:
        db.add(WatchList(asset_id=asset_id, user_id=current_user.id))
        await db.commit()
    except IntegrityError:
        await db.rollback()

    back = request.headers.get("referer", "/assets?filter=watchlist")
    return RedirectResponse(url=back, status_code=303)

@router.get("/delete_from_watchlist/{asset_id}")
async def delete_from_watchlist(request: Request, asset_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_from_token)):

    await db.execute(delete(WatchList).where(WatchList.asset_id == asset_id, WatchList.user_id == current_user.id))
    await db.commit()

    back = request.headers.get("referer", "/assets?filter=watchlist")
    return RedirectResponse(url=back, status_code=303)

@router.get("/populate_assets")
async def get_assets(request: Request, db: AsyncSession = Depends(get_db)):
    
    await populate_assets(db)

    return RedirectResponse(url="/assets", status_code=303)

@router.get("/populate_prices")
async def get_prices(request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    
    background_tasks.add_task(populate_prices, db)

    return RedirectResponse(url="/assets", status_code=303)