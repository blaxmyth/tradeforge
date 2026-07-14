import asyncio
import threading # Required for cross-thread synchronization
import datetime # NEW: Added for time and date operations
from alpaca.data.live import StockDataStream
from config import * # Assuming ALPACA_KEY and ALPACA_SECRET
from db.models import Asset, AssetPrice, AssetStrategy, Strategy, WatchList
from db.database import async_session_maker # NOTE: This must be configured as a SYNCHRONOUS session maker for this fix to work (e.g., using psycopg2, not asyncpg)
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from strats.opening_range_strategy import check_bar
import pytz
import time # Added for simple retry mechanism

# Initialize the stream client
stream = StockDataStream(ALPACA_KEY, ALPACA_SECRET)

# Global map to store Asset Symbol -> Asset ID. 
# This is fetched once at startup to avoid concurrent queries, but we rely on asset population script.
ASSET_MAP = {} 
SYMBOLS_TO_SUBSCRIBE = [] # Used only for the initial subscription list

# Global variable to hold the currently active subscription set for comparison
CURRENT_SUBSCRIPTION_SET = set() 

# CRITICAL FIX: Global THREADING lock to serialize database write operations 
# across different threads (where Alpaca stream runs handlers).
THREAD_LOCK = threading.Lock() 

# --- NEW MARKET CHECK CONFIGURATION ---
NYSE_TZ = pytz.timezone('America/New_York')
MARKET_CLOSE_HOUR = 16 # 4 PM ET
MARKET_CLOSE_MINUTE = 0 # 00 minutes
# Flag to prevent spamming the "Market Closed" log message every minute
MARKET_CLOSED_LOGGED = False 
# ------------------------------------

def _fetch_subscribed_symbols_sync() -> set:
    """Returns the union of watchlist symbols and strategy-linked symbols."""
    with async_session_maker() as session:
        watchlist_symbols = {
            entry.asset.symbol.upper()
            for entry in session.execute(
                select(WatchList).options(selectinload(WatchList.asset))
            ).scalars().all()
            if entry.asset
        }
        strategy_symbols = {
            row[0].upper()
            for row in session.execute(
                select(Asset.symbol)
                .join(AssetStrategy, AssetStrategy.asset_id == Asset.id)
            ).fetchall()
        }
    return watchlist_symbols | strategy_symbols

def initialize_asset_data_sync():
    """
    Initializes global ASSET_MAP and the initial CURRENT_SUBSCRIPTION_SET.
    This runs once at startup.
    """
    global ASSET_MAP, SYMBOLS_TO_SUBSCRIBE, CURRENT_SUBSCRIPTION_SET
    
    # We use the session maker as a synchronous context manager here
    with async_session_maker() as session:
        # --- 1. Get subscription symbols (watchlist ∪ strategy) ---
        initial_symbols      = _fetch_subscribed_symbols_sync()
        CURRENT_SUBSCRIPTION_SET = initial_symbols
        SYMBOLS_TO_SUBSCRIBE = list(initial_symbols)

        print(f"Initial subscribed symbols ({len(SYMBOLS_TO_SUBSCRIBE)}): {SYMBOLS_TO_SUBSCRIBE}")

        # --- 2. Create Asset ID Map ---
        asset_result = session.execute(select(Asset))
        ASSET_MAP = {a.symbol: a.id for a in asset_result.scalars()}

        print(f"Asset ID map created with {len(ASSET_MAP)} entries.")


def _insert_bar_data_sync(bar):
    """
    Core database insertion logic, now entirely SYNCHRONOUS (blocking).
    """
    asset_id = ASSET_MAP.get(bar.symbol)
    
    if not asset_id:
        print(f"Symbol not found in ASSET_MAP: {bar.symbol}. Skipping insertion.")
        return
    
    # We will attempt insertion multiple times to overcome transient DB errors
    max_retries = 3
    for attempt in range(max_retries):
        # Use the session maker as a synchronous context manager
        with async_session_maker() as session:
            try:
                # Prepare data: Convert the Alpaca timestamp to US/Eastern timezone and remove tzinfo for DB insertion
                bar.timestamp = bar.timestamp.astimezone(pytz.timezone("US/Eastern")).replace(tzinfo=None)
        
                candle = AssetPrice(
                    asset_id=asset_id,
                    datetime=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume
                )
        
                session.add(candle)
                session.commit() # SYNCHRONOUS commit
                print(f"[BAR] {bar.symbol} @ {bar.timestamp}")
                return # Success
                
            except Exception as e:
                session.rollback() # SYNCHRONOUS rollback
                # Check for the specific error that indicates concurrency conflict
                error_message = str(e)
                if "InterfaceError" in error_message or "attached to a different loop" in error_message:
                    # Transient errors can still occur in blocking I/O, so we keep the time.sleep
                    print(f"Transient DB Error for {bar.symbol} (Attempt {attempt+1}/{max_retries}): {e}. Retrying in 0.2s (Blocking).")
                    time.sleep(0.2)
                else:
                    # Log and break if it's a permanent error (e.g., schema violation)
                    print(f"Permanent Error inserting bar for {bar.symbol}: {e}")
                    break
    
    if attempt == max_retries - 1:
        print(f"FATAL: Failed to insert bar for {bar.symbol} after {max_retries} attempts.")

def _sync_locked_execution(bar):
    """
    Acquires the thread lock and runs the pure synchronous insertion logic,
    then triggers the opening range signal check outside the lock.
    """
    if not THREAD_LOCK.acquire(timeout=5):
        print(f"FATAL: Could not acquire lock for {bar.symbol}. Skipping insertion.")
        return

    inserted = False
    bar_dt   = None
    try:
        _insert_bar_data_sync(bar)
        inserted = True
        bar_dt   = bar.timestamp  # already converted to ET naive by _insert_bar_data_sync
    except Exception as e:
        print(f"FATAL ERROR during isolated insertion for {bar.symbol}: {e}")
    finally:
        THREAD_LOCK.release()

    # Run signal check after releasing the lock so other bars aren't blocked
    if inserted and bar_dt is not None:
        try:
            check_bar(bar.symbol, bar_dt)
        except Exception as e:
            print(f"[ORS] check_bar error for {bar.symbol}: {e}")

async def on_minute_bar(bar): 
    """
    Asynchronous callback function executed by the Alpaca stream.
    Delegates the thread-safe, SYNCHRONOUS execution to a separate thread.
    """
    await asyncio.to_thread(_sync_locked_execution, bar)

def _check_and_update_subscription_sync():
    """
    Fetches the latest watchlist + strategy symbols and updates Alpaca subscriptions.
    This function runs periodically in the polling thread.
    """
    global CURRENT_SUBSCRIPTION_SET

    latest = _fetch_subscribed_symbols_sync()

    to_unsubscribe = list(CURRENT_SUBSCRIPTION_SET - latest)
    to_subscribe   = list(latest - CURRENT_SUBSCRIPTION_SET)

    if to_subscribe or to_unsubscribe:
        print("-" * 50)
        print(f"Subscription change detected at {time.strftime('%Y-%m-%d %H:%M:%S')}")

        if to_unsubscribe:
            stream.unsubscribe_bars(*to_unsubscribe)
            print(f"UNSUBSCRIBED: {to_unsubscribe}")

        if to_subscribe:
            stream.subscribe_bars(on_minute_bar, *to_subscribe)
            print(f"SUBSCRIBED: {to_subscribe}")

        CURRENT_SUBSCRIPTION_SET = latest
        print(f"Active subscriptions: {len(CURRENT_SUBSCRIPTION_SET)}")

def _poll_for_watchlist_changes(interval_seconds=60):
    """
    Runs in a dedicated, infinite thread to periodically check for DB changes 
    and log market status.
    """
    global CURRENT_SUBSCRIPTION_SET, MARKET_CLOSED_LOGGED # Need to access and modify global flag

    print(f"Starting watchlist polling thread every {interval_seconds} seconds.")
    # Wait a short period to ensure the main stream loop is running before the first check
    time.sleep(1) 
    while True:
        try:
            # 1. Check Market Status
            now_et = datetime.datetime.now(NYSE_TZ)
            
            # Check if current time is 4 PM ET or later
            market_closed = now_et.hour >= MARKET_CLOSE_HOUR and now_et.minute >= MARKET_CLOSE_MINUTE

            if market_closed:
                if not MARKET_CLOSED_LOGGED:
                    # Log only once when the market first closes
                    print("-" * 50)
                    print(f"MARKET STATUS: Stock market is currently closed (After 4:00 PM ET). Data streaming may be inactive.")
                    print("-" * 50)
                    MARKET_CLOSED_LOGGED = True
            else:
                # If market is open, reset the flag so the message can be logged again next close
                MARKET_CLOSED_LOGGED = False

            # 2. Check and Update Watchlist
            _check_and_update_subscription_sync()
            
        except Exception as e:
            # Log the polling failure but keep the thread alive
            print(f"Error during watchlist polling: {e}")
            
        time.sleep(interval_seconds)

# --- Main Execution Logic ---

def start_stream():
    """
    Synchronous wrapper to handle initialization, start the polling thread, 
    and start the blocking stream.
    """
    
    # 1. Initialize data using the synchronous function directly
    try:
        initialize_asset_data_sync() 
    except Exception as e:
        print(f"CRITICAL ERROR during initialization: {e}")
        return # Exit if initialization fails

    if CURRENT_SUBSCRIPTION_SET:
        # 2. Start the Polling Thread (Daemon=True means it stops when the main thread stops)
        polling_thread = threading.Thread(target=_poll_for_watchlist_changes, daemon=True)
        polling_thread.start()
        
        # 3. Initial Subscribe to the fetched list of symbols
        stream.subscribe_bars(on_minute_bar, *SYMBOLS_TO_SUBSCRIBE) 
        
        # 4. Start the blocking stream.run() in the main thread.
        print("Starting Alpaca Stock Data Stream (Blocking, Dedicated Process)...")
        stream.run() 
    else:
        print("No symbols to subscribe (watchlist and strategies are empty). Not starting the data stream.")

if __name__ == "__main__":
    while True:
        try:
            start_stream()
            break  # clean exit
        except KeyboardInterrupt:
            print("\nScript interrupted by user.")
            break
        except Exception as e:
            msg = str(e).lower()
            if "connection limit exceeded" in msg:
                # Alpaca keeps the old WebSocket alive for ~60s after a crash.
                # Retrying immediately just loops — wait it out.
                print(f"[STREAM] Alpaca connection limit exceeded. Waiting 60s for old connection to expire...")
                time.sleep(60)
            else:
                print(f"[STREAM] Unexpected error: {e}. Retrying in 10s...")
                time.sleep(10)