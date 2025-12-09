from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date
from config import *
from db.models import *
from db.database import *
from sqlalchemy.future import select
from web.auth.auth import *

templates = Jinja2Templates(directory="/app/web/templates")
router = APIRouter(
    include_in_schema=False,
    dependencies=[Depends(get_current_user_from_token)]
)

# @router.post("/apply_strategy")
# async def apply_strategy(request: Request, strategy_id: int = Form(...), stock_id: int = Form(...), db: Session = Depends(get_db)):
#     try:
        
#         connection = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

#         cursor = connection.cursor(cursor_factory=psycopg2.extras.DictCursor)

#         cursor.execute("""
#             INSERT INTO stock_strategy VALUES (%s, %s)
#         """, (stock_id, strategy_id,))

#         connection.commit()

#         return RedirectResponse(url=f"/strategy/{strategy_id}", status_code=303)
#     except Exception as e:
#         return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
   

# @router.post("/delete_strategy")
# async def apply_strategy(request: Request, strategy_id: int = Form(...), stock_id: int = Form(...), db: Session = Depends(get_db)):
#     try:
#         token = request.cookies.get("access_token")
#         scheme, param = get_authorization_scheme_param(token)  # scheme will hold "Bearer" and param will hold actual token value
#         current_user: User = await get_current_user_from_token(token=param, db=db) #get user(email) from token
        
#         connection = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

#         cursor = connection.cursor(cursor_factory=psycopg2.extras.DictCursor)

#         cursor.execute("""
#             DELETE FROM stock_strategy
#             WHERE stock_id = %s AND strategy_id = %s
#         """, (stock_id, strategy_id,))

#         connection.commit()

#         return RedirectResponse(url=f"/strategy/{strategy_id}", status_code=303)
#     except Exception as e:
#         return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND) 

# @router.get("/strategy/{strategy_id}")
# async def strategy(request: Request, strategy_id, db: Session = Depends(get_db)):

#     token = request.cookies.get("access_token")
#     scheme, param = get_authorization_scheme_param(token)  # scheme will hold "Bearer" and param will hold actual token value
#     current_user: User = await get_current_user_from_token(token=param, db=db) #get user(email) from token
    
#     connection = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

#     cursor = connection.cursor(cursor_factory=psycopg2.extras.DictCursor)

#     cursor.execute("""
#         SELECT id, name FROM strategy WHERE id = %s
#     """, (strategy_id,))

#     strategy = cursor.fetchone()

#     cursor.execute("""
#         SELECT id, symbol, name, exchange 
#         FROM stock 
#         JOIN stock_strategy ON stock.id = stock_strategy.stock_id
#         WHERE strategy_id = %s
#     """, (strategy_id,))

#     stocks = cursor.fetchall()

#     return templates.TemplateResponse("strategy.html", {"request": request, "stocks": stocks, "strategy": strategy, "user" : current_user.username})


@router.get("/strategies")
async def strategies(request: Request, db: AsyncSession = Depends(get_db), context: dict = Depends(get_authenticated_template_context)):

    query = (
            select(Strategy)
        )
    result = await db.execute(query)

    strategies = result.scalars().all()

    return templates.TemplateResponse("strategies.html", {"request": request, "strategies": strategies, **context})
    
