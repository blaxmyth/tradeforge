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

    # ── watchlist + latest two prices per asset ───────────────────────────────
    watchlist = (await db.scalars(
        select(WatchList)
        .where(WatchList.user_id == current_user.id)
        .options(selectinload(WatchList.asset))
        .order_by(WatchList.id)
    )).all()

    watchlist_data = []
    if watchlist:
        asset_ids = [w.asset_id for w in watchlist]

        ranked = (
            select(
                AssetPrice.asset_id,
                AssetPrice.close,
                AssetPrice.datetime,
                func.row_number().over(
                    partition_by=AssetPrice.asset_id,
                    order_by=AssetPrice.datetime.desc(),
                ).label("rn"),
            )
            .where(AssetPrice.asset_id.in_(asset_ids))
            .subquery("ranked")
        )
        price_rows = (await db.execute(
            select(ranked.c.asset_id, ranked.c.close, ranked.c.datetime)
            .where(ranked.c.rn <= 2)
            .order_by(ranked.c.asset_id, ranked.c.datetime.desc())
        )).fetchall()

        price_map: dict[int, list] = defaultdict(list)
        for r in price_rows:
            price_map[r.asset_id].append(r.close)

        for w in watchlist:
            prices = price_map.get(w.asset_id, [])
            latest = prices[0] if prices else None
            prev   = prices[1] if len(prices) > 1 else None
            pct    = round((latest - prev) / prev * 100, 2) if latest and prev else None
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
