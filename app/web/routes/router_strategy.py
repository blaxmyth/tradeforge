from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from datetime import date
from config import *
from db.models import *
from db.database import *
from sqlalchemy.future import select
from sqlalchemy import delete
from web.auth.auth import *

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
    strategy_id: int, # Use type hint for clarity
    db: AsyncSession = Depends(get_db),
    context: dict = Depends(get_authenticated_template_context) # Use the context dependency for user/auth details
):
    
    # 1. Fetch the Strategy object by ID
    # This replaces the psycopg2 fetchone() for the strategy
    strategy_query = select(Strategy).where(Strategy.id == strategy_id)
    strategy = await db.scalar(strategy_query)

    if not strategy:
        # Handle case where strategy is not found (e.g., raise HTTP 404)
        pass 
    
    assets_query = (
        select(Asset)
        .join(AssetStrategy, AssetStrategy.asset_id == Asset.id)
        .where(AssetStrategy.strategy_id == strategy_id)
    )
    
    # Execute the query and get all the Asset objects
    assets_result = await db.scalars(assets_query)
    assets = assets_result.all()
    
    return templates.TemplateResponse(
        "strategy_detail.html", 
        {
            "request": request, 
            "assets": assets, 
            "strategy": strategy,
            **context
        }
    )


@router.get("/strategies")
async def strategies(request: Request, db: AsyncSession = Depends(get_db), context: dict = Depends(get_authenticated_template_context)):

    query = (
            select(Strategy)
        )
    result = await db.execute(query)

    strategies = result.scalars().all()

    return templates.TemplateResponse("strategies.html", {"request": request, "strategies": strategies, **context})
    
