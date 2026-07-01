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
    try:
        # 1. Create a new AssetStrategy object (the join table entry)
        new_link = AssetStrategy(
            asset_id=asset_id, 
            strategy_id=strategy_id
        )

        # 2. Add the new object to the session and commit
        db.add(new_link)
        await db.commit() # This executes the INSERT operation

        # 3. Redirect to the strategy detail page to show the added asset
        return RedirectResponse(url=f"/strategy/{strategy_id}", status_code=status.HTTP_303_SEE_OTHER)
        
    except IntegrityError:
        # Catch potential database errors (e.g., asset already linked, or non-existent FK)
        await db.rollback()
        # Log the error, and redirect back with a possible error message (e.g., via session)
        print(f"Error: Asset {asset_id} is already linked to strategy {strategy_id} or foreign key constraint failed.")
        return RedirectResponse(url=f"/strategy/{strategy_id}?error=link_failed", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        # General error handling (e.g., session expired, database unavailable)
        print(f"An unexpected error occurred: {e}")
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
   

@router.post("/delete_strategy")
async def delete_strategy(
    strategy_id: int = Form(...), 
    asset_id: int = Form(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Construct the delete query to remove the link in the AssetStrategy table
        # We target the specific combination of asset_id and strategy_id
        query = delete(AssetStrategy).where(
            AssetStrategy.asset_id == asset_id, 
            AssetStrategy.strategy_id == strategy_id
        )

        # 2. Execute the query
        await db.execute(query)

        # 3. Commit the change
        await db.commit() 

        # 4. Redirect to the strategy detail page to show the updated list
        return RedirectResponse(url=f"/strategy/{strategy_id}", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        # Handle general errors (e.g., database connection issues)
        await db.rollback()
        print(f"An unexpected error occurred during deletion: {e}")
        # Redirect back to the strategy page with an error status
        return RedirectResponse(url=f"/strategy/{strategy_id}?error=delete_failed", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/strategy/{strategy_id}")
async def strategy_detail(
    request: Request,
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    context: dict = Depends(get_authenticated_template_context),
):
    strategy = await db.scalar(select(Strategy).where(Strategy.id == strategy_id))

    assets = (await db.scalars(
        select(Asset)
        .join(AssetStrategy, AssetStrategy.asset_id == Asset.id)
        .where(AssetStrategy.strategy_id == strategy_id)
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
    
