import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import URL
from config import *

url = URL.create(
    drivername="postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    database=DB_NAME,
    port=5432
)

engine = create_async_engine(url, echo=True)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async_session_maker = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)