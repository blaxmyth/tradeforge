"""
Opening Range Strategy
======================
One strategy, both directions. On each day, the engine computes the opening
range (OR), then scans bars after the OR window for whichever side breaks first:

  close > OR high * (1 + buffer/100)  →  BREAKOUT  (long signal)
  close < OR low  * (1 - buffer/100)  →  BREAKDOWN (short signal)

Whichever fires first is the trade for that day. One signal per asset per day.

Config params (stored in AssetStrategy.config JSON):

  or_start        HH:MM ET  Start of OR window          (default 09:30)
  or_end          HH:MM ET  End of OR window             (default 09:45)
  timeframe       str       1min | 5min | 15min | 1hr   (default 1min)
  buffer_pct      float     % beyond OR level required   (default 0.0)
  min_range_pct   float     Skip day if OR too narrow    (default 0.0)
  volume_mult     float     N× avg OR volume required; 0=off (default 0.0)
  stop_loss_pct   float     Simulated stop from entry %  (default 1.0)
  take_profit_pct float     Simulated target from entry % (default 2.0)

Sweep grid: or_end × buffer_pct × min_range_pct  →  48 combinations.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import product
from typing import Any

import redis as redis_lib
from sqlalchemy import text
from sqlalchemy.future import select

from config import DISCORD_WEBHOOK, REDIS_HOST, REDIS_PORT
from db.database import SyncSessionLocal
from db.models import Asset, AssetStrategy, SignalLog, Strategy

TIMEFRAME_TABLE: dict[str, tuple[str, str]] = {
    "1min":  ("asset_price",       "datetime"),
    "5min":  ("asset_price_5min",  "bucket"),
    "15min": ("asset_price_15min", "bucket"),
    "1hr":   ("asset_price_1hr",   "bucket"),
}

DEFAULT_CONFIG: dict[str, Any] = {
    "or_start":        "09:30",
    "or_end":          "09:45",
    "timeframe":       "1min",
    "buffer_pct":      0.0,
    "min_range_pct":   0.0,
    "volume_mult":     0.0,
    "stop_loss_pct":   1.0,
    "take_profit_pct": 2.0,
}

SWEEP_GRID: dict[str, list] = {
    "or_end":        ["09:45", "10:00", "10:15", "10:30"],
    "buffer_pct":    [0.0, 0.1, 0.25, 0.5],
    "min_range_pct": [0.0, 0.25, 0.5],
}

STRATEGY_NAME = "opening_range"

_redis = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _merge(override: dict | None) -> dict:
    return {**DEFAULT_CONFIG, **(override or {})}


def _parse_time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def _send_notification(message: str) -> None:
    if DISCORD_WEBHOOK:
        try:
            from discordwebhook import Discord
            Discord(url=DISCORD_WEBHOOK).post(content=message)
        except Exception as exc:
            print(f"[ORS] Discord error: {exc}")
    try:
        from scripts.send_mail import notify
        notify(message)
    except Exception as exc:
        print(f"[ORS] Email error: {exc}")


# ── core simulation ───────────────────────────────────────────────────────────

def _simulate_day(day_bars: list, cfg: dict) -> dict | None:
    """
    Simulate the strategy on a single day's bars.
    Checks BOTH directions — returns whichever side breaks first, or None.
    Bars are tuples: (t, open, high, low, close, volume)
    """
    or_start_t = _parse_time(cfg["or_start"])
    or_end_t   = _parse_time(cfg["or_end"])

    or_bars    = [b for b in day_bars if or_start_t <= b[0].time() <= or_end_t]
    after_bars = [b for b in day_bars if b[0].time() > or_end_t]

    if len(or_bars) < 2 or not after_bars:
        return None

    or_high = max(b[2] for b in or_bars)
    or_low  = min(b[3] for b in or_bars)
    or_mid  = (or_high + or_low) / 2.0

    # Skip days where the opening range is too narrow
    if cfg["min_range_pct"] > 0 and or_mid > 0:
        if (or_high - or_low) / or_mid * 100 < cfg["min_range_pct"]:
            return None

    avg_vol    = sum(b[5] or 0 for b in or_bars) / len(or_bars)
    buffer     = cfg["buffer_pct"] / 100.0
    vol_thresh = avg_vol * cfg["volume_mult"] if cfg["volume_mult"] > 0 else 0.0

    trigger_hi = or_high * (1.0 + buffer)
    trigger_lo = or_low  * (1.0 - buffer)

    # Scan post-OR bars — first side to break wins
    direction  = None
    entry_bar  = None
    for bar in after_bars:
        t, o, h, l, close, vol = bar
        vol = vol or 0
        if close > trigger_hi:
            if vol_thresh > 0 and vol < vol_thresh:
                continue
            direction, entry_bar = "breakout", bar
            break
        elif close < trigger_lo:
            if vol_thresh > 0 and vol < vol_thresh:
                continue
            direction, entry_bar = "breakdown", bar
            break

    if entry_bar is None:
        return None

    entry_price = entry_bar[4]
    entry_idx   = after_bars.index(entry_bar)

    tp_pct = cfg["take_profit_pct"] / 100.0
    sl_pct = cfg["stop_loss_pct"]   / 100.0

    if direction == "breakout":
        tp_price = entry_price * (1.0 + tp_pct)
        sl_price = entry_price * (1.0 - sl_pct)
    else:
        tp_price = entry_price * (1.0 - tp_pct)
        sl_price = entry_price * (1.0 + sl_pct)

    outcome    = "timeout"
    exit_price = after_bars[-1][4]

    for bar in after_bars[entry_idx + 1:]:
        t, o, h, l, close, vol = bar
        if direction == "breakout":
            if h >= tp_price:
                outcome, exit_price = "win",  tp_price; break
            if l <= sl_price:
                outcome, exit_price = "loss", sl_price; break
        else:
            if l <= tp_price:
                outcome, exit_price = "win",  tp_price; break
            if h >= sl_price:
                outcome, exit_price = "loss", sl_price; break

    raw_pct    = (exit_price - entry_price) / entry_price * 100.0
    pct_change = raw_pct if direction == "breakout" else -raw_pct

    return {
        "date":        day_bars[0][0].date().isoformat(),
        "direction":   direction,
        "entry_time":  entry_bar[0].strftime("%H:%M"),
        "entry_price": round(entry_price, 4),
        "exit_price":  round(exit_price,  4),
        "pct_change":  round(pct_change,  3),
        "outcome":     outcome,
        "or_high":     round(or_high, 4),
        "or_low":      round(or_low,  4),
    }


# ── aggregation ───────────────────────────────────────────────────────────────

def _agg_trades(trades: list[dict]) -> dict:
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "timeouts": 0,
                "win_rate": 0.0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
                "profit_factor": 0.0}
    wins     = [t for t in trades if t["outcome"] == "win"]
    losses   = [t for t in trades if t["outcome"] == "loss"]
    timeouts = [t for t in trades if t["outcome"] == "timeout"]
    avg_win  = sum(t["pct_change"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss = sum(t["pct_change"] for t in losses) / len(losses) if losses else 0.0
    gp = sum(t["pct_change"] for t in wins)
    gl = abs(sum(t["pct_change"] for t in losses + timeouts))
    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
    return {
        "total":          len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "timeouts":       len(timeouts),
        "win_rate":       round(len(wins) / len(trades) * 100, 1),
        "avg_win_pct":    round(avg_win,  3),
        "avg_loss_pct":   round(avg_loss, 3),
        "profit_factor":  round(pf, 2),
    }


def _aggregate(trades: list[dict]) -> dict:
    overall = _agg_trades(trades)
    overall["total_signals"] = overall.pop("total")
    bo = _agg_trades([t for t in trades if t["direction"] == "breakout"])
    bd = _agg_trades([t for t in trades if t["direction"] == "breakdown"])
    overall["by_direction"] = {"breakout": bo, "breakdown": bd}
    overall["trades"] = trades
    return overall


# ── data fetch ────────────────────────────────────────────────────────────────

def _fetch_days_map(
    symbol: str, timeframe: str, lookback_days: int
) -> tuple[dict[date, list], str | None]:
    if timeframe not in TIMEFRAME_TABLE:
        return {}, f"Unknown timeframe '{timeframe}'"

    table, time_col = TIMEFRAME_TABLE[timeframe]
    since = datetime.now() - timedelta(days=lookback_days + 14)

    with SyncSessionLocal() as session:
        asset = session.execute(
            select(Asset).where(Asset.symbol == symbol.upper())
        ).scalar_one_or_none()
        if not asset:
            return {}, f"Symbol '{symbol}' not found"

        rows = session.execute(text(f"""
            SELECT {time_col} AS t, open, high, low, close, volume
            FROM {table}
            WHERE asset_id = :aid AND {time_col} >= :since
            ORDER BY {time_col} ASC
        """), {"aid": asset.id, "since": since}).fetchall()

    days_map: dict[date, list] = {}
    for row in rows:
        days_map.setdefault(row[0].date(), []).append(row)

    return days_map, None


# ── public API ────────────────────────────────────────────────────────────────

def backtest(symbol: str, config: dict | None = None, days: int = 60) -> dict:
    """
    Run the strategy against the last `days` trading days.
    Returns combined + per-direction metrics and the per-trade log.
    """
    cfg = _merge(config)
    days_map, err = _fetch_days_map(symbol, cfg["timeframe"], days)
    if err:
        return {"error": err}

    trading_days = sorted(days_map.keys())[-days:]
    trades = [
        t for d in trading_days
        if (t := _simulate_day(days_map[d], cfg)) is not None
    ]
    return _aggregate(trades)


def sweep(symbol: str, base_config: dict | None = None, days: int = 60) -> list[dict]:
    """
    Grid search: 4 or_ends × 4 buffers × 3 min_range_pcts = 48 combos.
    Fetches data once, simulates all combos in memory.
    Returns list sorted by profit_factor desc.
    """
    base     = _merge(base_config)
    days_map, err = _fetch_days_map(symbol, base["timeframe"], days)
    if err:
        return [{"error": err}]

    trading_days = sorted(days_map.keys())[-days:]
    keys   = list(SWEEP_GRID.keys())
    combos = list(product(*SWEEP_GRID.values()))

    results = []
    for combo in combos:
        override = dict(zip(keys, combo))
        cfg      = {**base, **override}
        trades   = [
            t for d in trading_days
            if (t := _simulate_day(days_map[d], cfg)) is not None
        ]
        result           = _aggregate(trades)
        result["config"] = override
        results.append(result)

    return sorted(results, key=lambda x: (x["profit_factor"], x["win_rate"]), reverse=True)


# ── live runner (Celery) ──────────────────────────────────────────────────────

def opening_range_strategy() -> None:
    """
    Called every minute by the Celery beat scheduler during market hours.
    Checks both breakout and breakdown for each asset assigned to 'opening_range'.
    Fires the first side that breaks, then deduplicates for the rest of the day.
    """
    import pytz
    ET     = pytz.timezone("US/Eastern")
    now_et = datetime.now(ET)
    today  = now_et.date()

    if today.weekday() >= 5:
        return
    cur = now_et.time().replace(tzinfo=None)
    if cur < time(9, 45) or cur >= time(16, 0):
        return

    with SyncSessionLocal() as session:
        strategy_row = session.execute(
            select(Strategy.config).where(Strategy.name == STRATEGY_NAME)
        ).scalar_one_or_none()
        cfg = _merge(strategy_row)

        symbols = session.execute(
            select(Asset.symbol)
            .join(AssetStrategy, AssetStrategy.asset_id == Asset.id)
            .join(Strategy,      AssetStrategy.strategy_id == Strategy.id)
            .where(Strategy.name == STRATEGY_NAME)
        ).scalars().all()

    for symbol in symbols:
        if cfg["timeframe"] not in TIMEFRAME_TABLE:
            continue

        signal_key = f"ors:{STRATEGY_NAME}:{symbol}:{today}"
        if _redis.get(signal_key):
            continue

        table, time_col = TIMEFRAME_TABLE[cfg["timeframe"]]
        or_start_dt     = datetime.combine(today, _parse_time(cfg["or_start"]))

        with SyncSessionLocal() as session:
            day_bars = session.execute(text(f"""
                SELECT {time_col} AS t, open, high, low, close, volume
                FROM {table}
                WHERE asset_id = (SELECT id FROM asset WHERE symbol = :sym LIMIT 1)
                  AND {time_col} >= :start
                ORDER BY {time_col} ASC
            """), {"sym": symbol, "start": or_start_dt}).fetchall()

        trade = _simulate_day(day_bars, cfg)
        if not trade:
            print(f"[ORS] {symbol}: no signal yet")
            continue

        direction = trade["direction"]
        level     = trade["or_high"] if direction == "breakout" else trade["or_low"]
        side      = "above OR high" if direction == "breakout" else "below OR low"

        message = (
            f"[TradeForge] {direction.upper()}: {symbol}\n"
            f"Strategy   : {STRATEGY_NAME}\n"
            f"Entry (sim): ${trade['entry_price']:.2f} @ {trade['entry_time']} ET\n"
            f"Closed {side}: ${level:.2f}\n"
            f"OR range   : ${trade['or_low']:.2f} – ${trade['or_high']:.2f}\n"
            f"Config     : OR {cfg['or_start']}–{cfg['or_end']} | "
            f"buffer {cfg['buffer_pct']}% | tf {cfg['timeframe']}"
        )
        print(f"[ORS] SIGNAL — {message}")
        _send_notification(message)

        with SyncSessionLocal() as session:
            session.add(SignalLog(
                strategy_name   = STRATEGY_NAME,
                symbol          = symbol,
                direction       = direction,
                entry_price     = trade["entry_price"],
                or_high         = trade["or_high"],
                or_low          = trade["or_low"],
                entry_time      = trade["entry_time"],
                fired_at        = datetime.now(),
                config_snapshot = cfg,
            ))
            session.commit()

        ttl = int(
            (datetime.combine(today + timedelta(days=1), time(0, 0)) - datetime.now())
            .total_seconds()
        )
        _redis.setex(signal_key, max(ttl, 3600), "fired")
