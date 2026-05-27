import os
# We need both synchronous and asynchronous engine/session makers
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import URL
from config import * # Assuming DB_USER, DB_PASS, DB_HOST, DB_NAME are defined here

# --- 1. ASYNCHRONOUS Configuration (Used primarily by FastAPI/Routes) ---

# URL for the asynchronous PostgreSQL driver (asyncpg)
async_url = URL.create(
    drivername="postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    database=DB_NAME,
    port=5432
)

# Asynchronous engine
async_engine = create_async_engine(async_url, echo=True)

# Asynchronous Session Makers
AsyncSessionLocal = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

# This is the session maker used by FastAPI dependency injection
AsyncSessionMaker = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    class_=AsyncSession
)

# FastAPI dependency function
async def get_db():
    async with AsyncSessionMaker() as session:
        yield session

# --- 2. SYNCHRONOUS Configuration (Used by stream.py and other worker scripts) ---

# URL for the synchronous PostgreSQL driver (psycopg2)
sync_url = URL.create(
    drivername="postgresql+psycopg2",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    database=DB_NAME,
    port=5432
)

# Synchronous engine
sync_engine = create_engine(sync_url, echo=True)

# Synchronous session maker (for use in stream.py)
# NOTE: This yields synchronous sessions which must be used outside of the main async loop.
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)

# --- 3. EXPORTS (CRITICAL FIX FOR stream.py) ---
# We export the SYNCHRONOUS session maker using the name that stream.py expects.
# stream.py will now receive SyncSessionLocal (a synchronous maker) when it imports
# 'async_session_maker', allowing the code in stream.py to run blocking I/O successfully.
async_session_maker = SyncSessionLocal

# We export the asynchronous engine for use in model creation/migrations
engine = async_engine