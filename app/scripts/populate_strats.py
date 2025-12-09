from sqlalchemy import select
from config import *
from db.models import *
from db.database import *
import asyncio

async def populate_strats(db: AsyncSession):

    existing_strats = []

    query = select(Strategy.name)
    result = await db.execute(query)

    for row in result:
        existing_strats.append(row[0])

    strategies = ['opening_range_breakout', 'opening_range_breakdown']

    for strategy in strategies:
        if strategy in existing_strats:
            print(f"{strategy} already exists in db")
        else:
            print(f'adding {strategy} to db')

            strat = Strategy(name=strategy)
            db.add(strat)
        
    await db.commit()

async def _run():
    async with async_session_maker() as session:
        await populate_strats(session)

if __name__ == "__main__":
    asyncio.run(_run())
