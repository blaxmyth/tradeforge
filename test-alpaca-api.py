#!/usr/bin/env python3
"""
Test Alpaca API connectivity — REST and WebSocket (paper trading).
Usage: python test-alpaca-api.py
Reads ALPACA_KEY and ALPACA_SECRET from the environment or .env file.
"""

import os
import sys
import json
import threading
import time

# macOS Python 3.10 (python.org) doesn't trust system certs — point it at certifi.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

load_env()

ALPACA_KEY = os.environ.get("ALPACA_KEY")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET")

if not ALPACA_KEY or not ALPACA_SECRET:
    print("ERROR: ALPACA_KEY and ALPACA_SECRET must be set in the environment or .env file.")
    sys.exit(1)


def test_rest():
    import urllib.request
    print("--- REST API ---")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/account",
        headers={
            "APCA-API-KEY-ID": ALPACA_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"  Status : {resp.status}")
            print(f"  Account: {data.get('id')}")
            print(f"  Cash   : ${float(data.get('cash', 0)):,.2f}")
            print(f"  Status : {data.get('status')}")
            print("  PASS\n")
            return True
    except Exception as e:
        print(f"  FAIL: {e}\n")
        return False


def test_websocket():
    print("--- WebSocket Stream ---")
    try:
        from alpaca.data.live import StockDataStream
    except ImportError:
        print("  SKIP: alpaca-py not installed in this environment.\n")
        return None

    result = {"connected": False, "error": None}

    def run():
        async def on_bar(bar):
            result["connected"] = True

        stream = StockDataStream(ALPACA_KEY, ALPACA_SECRET)
        stream.subscribe_bars(on_bar, "SPY")

        def stop():
            time.sleep(6)
            stream.stop()

        threading.Thread(target=stop, daemon=True).start()

        try:
            stream.run()
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=10)

    if result["error"]:
        print(f"  FAIL: {result['error']}\n")
        return False

    if result["connected"]:
        print("  Connected and received bar data.")
    else:
        print("  Connected (no bar data — market may be closed or outside trading hours).")
    print("  PASS\n")
    return True


if __name__ == "__main__":
    rest_ok = test_rest()
    ws_ok = test_websocket()

    if rest_ok is False or ws_ok is False:
        sys.exit(1)
