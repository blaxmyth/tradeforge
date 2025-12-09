import asyncio
import pandas as pd
from contextlib import asynccontextmanager
from config import *
from alpaca.broker import BrokerClient
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetStatus, AssetClass # Added AssetClass
from scripts.functions import *
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.models import Asset, Base 
from db.database import async_session_maker, engine


# Helper function to yield an AsyncSession for use outside of FastAPI dependencies
# We assume 'async_session_maker' is imported from db.database
@asynccontextmanager
async def get_session():
    """Provides a database session context manager."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def populate_assets(db: AsyncSession):
    
    print("--- Starting Asset Population Script ---")

    # Initialize Alpaca client
    trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET)

    # Define the asset classes we explicitly want to fetch
    # We use separate requests to avoid issues with non-standard Alpaca asset types
    TARGET_ASSET_CLASSES = [AssetClass.US_EQUITY, AssetClass.CRYPTO]
    assets = []
    
    try:
        # Fetch assets from Alpaca, filtered by class
        print("Fetching assets from Alpaca (filtered to US_EQUITY and CRYPTO)...")
        
        for target_class in TARGET_ASSET_CLASSES:
            print(f"  -> Fetching {target_class.value.upper()}...")
            search_params = GetAssetsRequest(
                status=AssetStatus.ACTIVE,
                asset_class=target_class
            )
            # The Alpaca SDK returns a list of Asset objects
            class_assets = trading_client.get_all_assets(search_params)
            assets.extend(class_assets)
            print(f"  -> Found {len(class_assets)} {target_class.value.upper()} assets.")
            
        print(f"Total found assets: {len(assets)}.")

    except Exception as e:
        print(f"Error: {e}")
        return

    # Check for existing assets to prevent duplicates
    query = select(Asset.symbol)
    result = await db.execute(query)
    existing_assets = {row[0] for row in result.all()}

    new_asset_count = 0
    # Removed unused variable: update_count

    for asset in assets:
        symbol = asset.symbol
        name = asset.name
        exchange = asset.exchange
        asset_class = asset.asset_class
        is_sp500 = False
        # NOTE: Uncomment sp500 and etfs logic if you implement those functions

        if symbol not in existing_assets:
            try:
                print(f"Inserting NEW asset: {symbol} - {name}")
                new_asset = Asset(
                    name=name,
                    symbol=symbol,
                    exchange=exchange,
                    asset_class=asset_class.value, # Use .value to get the string representation
                    is_sp500=is_sp500 # FIX: Default to False to satisfy non-nullable boolean requirement
                )
                db.add(new_asset)
                new_asset_count += 1
            except Exception as e:
                print(f"ERROR inserting asset {symbol}: {e}")
                # This could still be a Pydantic/SQLAlchemy validation error if 
                # your local Asset model's columns (e.g., 'asset_class') are defined 
                # as Enums that are still too strict.
        else:
            # Optionally, you might want to update existing asset data here
            print(f"{symbol} already exists in database. Skipping...")

    await db.commit()
    print("--- Asset Population Script Finished ---")
    print(f"Summary: Inserted {new_asset_count} new assets. Total processed: {len(assets)}")


# --- EXECUTION BLOCK (The fix) ---
async def main():
    """Main execution function to run the script."""
    
    # 1. Ensure tables exist (optional, but good for setup scripts)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # 2. Acquire a session and run the population function
    async with get_session() as db:
        await populate_assets(db)

if __name__ == "__main__":
    # This block is the standard entry point and runs the asynchronous 'main' function.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScript interrupted by user.")
    except Exception as e:
        print(f"An unexpected error occurred in main execution: {e}")