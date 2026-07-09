from collections import defaultdict
from datetime import datetime

import pytz
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from config import redis_client
from db.database import get_db
from db.models import Asset, AssetPrice, AssetStrategy, SignalLog, Strategy, WatchList
from web.auth.auth import get_authenticated_template_context, get_current_user_from_token
from db.models import User

router = APIRouter()
templates = Jinja2Templates(directory="/app/web/templates")

ET = pytz.timezone("US/Eastern")


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
    context: dict = Depends(get_authenticated_template_context),
):
    today = datetime.now(ET).date()

    # ── watchlist + day-over-day price change ─────────────────────────────────
    watchlist = (await db.scalars(
        select(WatchList)
        .where(WatchList.user_id == current_user.id)
        .options(selectinload(WatchList.asset))
        .order_by(WatchList.id)
    )).all()

    watchlist_data = []
    if watchlist:
        asset_ids = [w.asset_id for w in watchlist]

        # Last two daily closes per asset from the 1-day continuous aggregate
        daily_ranked = (await db.execute(text("""
            SELECT asset_id, close, bucket,
                   row_number() OVER (PARTITION BY asset_id ORDER BY bucket DESC) AS rn
            FROM asset_price_1day
            WHERE asset_id = ANY(:ids)
        """), {"ids": asset_ids})).fetchall()

        price_map: dict[int, list] = defaultdict(list)
        for r in daily_ranked:
            if r.rn <= 2:
                price_map[r.asset_id].append(r.close)

        # Fall back to 1-min bars for today's latest price if market is open
        latest_1min = (await db.execute(text("""
            SELECT DISTINCT ON (asset_id) asset_id, close
            FROM asset_price
            WHERE asset_id = ANY(:ids)
            ORDER BY asset_id, datetime DESC
        """), {"ids": asset_ids})).fetchall()
        latest_map = {r.asset_id: r.close for r in latest_1min}

        for w in watchlist:
            daily = price_map.get(w.asset_id, [])
            latest = latest_map.get(w.asset_id) or (daily[0] if daily else None)
            prev   = daily[1] if len(daily) > 1 else (daily[0] if daily else None)
            pct    = round((latest - prev) / prev * 100, 2) if latest and prev and prev != latest else None
            watchlist_data.append({
                "symbol": w.asset.symbol,
                "name":   w.asset.name,
                "price":  round(latest, 2) if latest else None,
                "change": pct,
            })

    # ── strategies with linked asset count ────────────────────────────────────
    asset_count_subq = (
        select(func.count(AssetStrategy.asset_id))
        .where(AssetStrategy.strategy_id == Strategy.id)
        .correlate(Strategy)
        .scalar_subquery()
    )
    strat_rows = (await db.execute(
        select(
            Strategy.id,
            Strategy.name,
            Strategy.config,
            asset_count_subq.label("asset_count"),
        )
        .order_by(Strategy.name)
    )).fetchall()

    strategies = [
        {"id": r.id, "name": r.name, "config": r.config, "asset_count": r.asset_count}
        for r in strat_rows
    ]

    # ── today's signals from signal_log ──────────────────────────────────────
    today_start = datetime.combine(today, datetime.min.time())
    signal_rows = (await db.execute(
        select(SignalLog)
        .where(SignalLog.fired_at >= today_start)
        .order_by(SignalLog.fired_at.desc())
    )).scalars().all()

    signals = [
        {
            "strategy":  s.strategy_name,
            "symbol":    s.symbol,
            "direction": s.direction,
            "price":     round(s.entry_price, 2) if s.entry_price else None,
            "fired_at":  s.fired_at.strftime("%H:%M") if s.fired_at else None,
        }
        for s in signal_rows
    ]

    return templates.TemplateResponse("index.html", {
        **context,
        "watchlist":  watchlist_data,
        "strategies": strategies,
        "signals":    signals,
        "today":      today.isoformat(),
    })


_TV_DEFAULTS = [
    {"proName": "FOREXCOM:SPXUSD", "title": "S&P 500"},
    {"proName": "FOREXCOM:NSXUSD", "title": "Nasdaq 100"},
    {"proName": "DJ:DJI",          "title": "Dow Jones"},
    {"proName": "TVC:VIX",         "title": "VIX"},
]

_TV_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}


@router.get("/api/watchlist/ticker")
async def watchlist_ticker(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Return watchlist assets as TradingView ticker-tape symbol objects."""
    rows = (await db.execute(
        select(Asset.symbol, Asset.name, Asset.exchange)
        .join(WatchList, WatchList.asset_id == Asset.id)
        .where(WatchList.user_id == current_user.id)
        .order_by(WatchList.id)
    )).fetchall()

    if not rows:
        return _TV_DEFAULTS

    symbols = []
    for r in rows:
        exchange = (r.exchange or "").upper()
        tv_sym   = f"{exchange}:{r.symbol}" if exchange in _TV_EXCHANGES else r.symbol
        symbols.append({"proName": tv_sym, "title": r.symbol})

    return symbols


@router.get("/ping-redis")
async def ping_redis():
    ping = await redis_client.ping()
    return {"ping": ping}
