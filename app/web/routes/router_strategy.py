from fastapi import APIRouter, Request, Depends, Form, Body
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from datetime import date
from config import *
from db.models import *
from db.database import *
from sqlalchemy.future import select
from sqlalchemy import delete, update
from web.auth.auth import *
from strats.opening_range_strategy import backtest, sweep, DEFAULT_CONFIG

templates = Jinja2Templates(directory="/app/web/templates")
router = APIRouter(
    include_in_schema=False,
    dependencies=[Depends(get_current_user_from_token)]
)

@router.post("/apply_strategy")
async def apply_strategy(
    strategy_id: int = Form(...),
    asset_id: int = Form(...),
    db: AsyncSession = Depends(get_db)
):
    strategy_name = await db.scalar(select(Strategy.name).where(Strategy.id == strategy_id))
    try:
        db.add(AssetStrategy(asset_id=asset_id, strategy_id=strategy_id))
        await db.commit()
        return RedirectResponse(url=f"/strategy/{strategy_name}", status_code=status.HTTP_303_SEE_OTHER)
    except IntegrityError:
        await db.rollback()
        return RedirectResponse(url=f"/strategy/{strategy_name}?error=link_failed", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.post("/delete_strategy")
async def delete_strategy(
    strategy_id: int = Form(...),
    asset_id: int = Form(...),
    db: AsyncSession = Depends(get_db)
):
    strategy_name = await db.scalar(select(Strategy.name).where(Strategy.id == strategy_id))
    try:
        await db.execute(delete(AssetStrategy).where(
            AssetStrategy.asset_id == asset_id,
            AssetStrategy.strategy_id == strategy_id
        ))
        await db.commit()
        return RedirectResponse(url=f"/strategy/{strategy_name}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        await db.rollback()
        print(f"An unexpected error occurred during deletion: {e}")
        return RedirectResponse(url=f"/strategy/{strategy_name}?error=delete_failed", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/strategy/{strategy_name}")
async def strategy_detail(
    request: Request,
    strategy_name: str,
    db: AsyncSession = Depends(get_db),
    context: dict = Depends(get_authenticated_template_context),
):
    strategy = await db.scalar(select(Strategy).where(Strategy.name == strategy_name))

    assets = (await db.scalars(
        select(Asset)
        .join(AssetStrategy, AssetStrategy.asset_id == Asset.id)
        .where(AssetStrategy.strategy_id == strategy.id)
        .order_by(Asset.symbol)
    )).all()

    global_config = {**DEFAULT_CONFIG, **(strategy.config or {})}

    return templates.TemplateResponse(
        "strategy_detail.html",
        {
            "request":       request,
            "strategy":      strategy,
            "assets":        [{"id": a.id, "symbol": a.symbol, "name": a.name} for a in assets],
            "global_config": global_config,
            **context,
        },
    )


@router.post("/api/strategy/{strategy_id}/config")
async def save_strategy_config(
    strategy_id: int,
    config: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Save the global strategy config — applies to all assets linked to this strategy."""
    await db.execute(
        update(Strategy).where(Strategy.id == strategy_id).values(config=config)
    )
    await db.commit()
    return JSONResponse(content={"ok": True})


@router.post("/api/asset/{symbol}/backtest")
async def run_backtest(symbol: str, body: dict = Body(...)):
    """
    Run the opening range backtest for one symbol.
    Body: {config (optional), days (optional)}
    Returns combined + per-direction metrics and trade log.
    """
    config = body.get("config")
    days   = int(body.get("days", 60))
    result = await run_in_threadpool(backtest, symbol, config, days)
    return JSONResponse(content=result)


@router.post("/api/asset/{symbol}/sweep")
async def run_sweep(symbol: str, body: dict = Body(...)):
    """
    Grid-search over OR end × buffer % × min range % (48 combos).
    Body: {base_config (optional), days (optional)}
    Returns list sorted by profit_factor desc.
    """
    base_config = body.get("base_config")
    days        = int(body.get("days", 60))
    results = await run_in_threadpool(sweep, symbol, base_config, days)
    return JSONResponse(content=results)


@router.get("/strategies")
async def strategies(request: Request, db: AsyncSession = Depends(get_db), context: dict = Depends(get_authenticated_template_context)):

    query = (
            select(Strategy)
        )
    result = await db.execute(query)

    strategies = result.scalars().all()

    return templates.TemplateResponse("strategies.html", {"request": request, "strategies": strategies, **context})
    
