from __future__ import annotations

from datetime import date, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)
from alpaca.trading.enums import ContractType, OrderSide, TimeInForce, OrderClass

from config import ALPACA_PAPER_KEY, ALPACA_PAPER_SECRET

_client: TradingClient | None = None


def _get_client() -> TradingClient:
    global _client
    if _client is None:
        _client = TradingClient(ALPACA_PAPER_KEY, ALPACA_PAPER_SECRET, paper=True)
    return _client


def _next_friday(ref: date | None = None) -> date:
    """Return the next Friday after ref (never the same day as ref)."""
    d = ref or date.today()
    days_ahead = (4 - d.weekday()) % 7  # Friday = weekday 4
    if days_ahead == 0:
        days_ahead = 7
    return d + timedelta(days=days_ahead)


def place_order(
    symbol: str,
    direction: str,
    entry_price: float,
    qty: float,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
) -> str | None:
    """
    Place a DAY limit order on the Alpaca paper account.
    Uses a bracket (stop + take profit) when both percentages are configured.
    Returns the Alpaca order ID, or None on failure.

    direction: 'breakout' (long) | 'breakdown' (short)
    """
    if not ALPACA_PAPER_KEY or not ALPACA_PAPER_SECRET:
        print("[ORDER] ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET not set — skipping.")
        return None

    side = OrderSide.BUY if direction == "breakout" else OrderSide.SELL

    if direction == "breakout":
        stop_price   = round(entry_price * (1 - stop_loss_pct   / 100), 2)
        target_price = round(entry_price * (1 + take_profit_pct / 100), 2)
    else:
        stop_price   = round(entry_price * (1 + stop_loss_pct   / 100), 2)
        target_price = round(entry_price * (1 - take_profit_pct / 100), 2)

    use_bracket = stop_loss_pct > 0 and take_profit_pct > 0

    params: dict = dict(
        symbol=symbol,
        qty=qty,
        side=side,
        time_in_force=TimeInForce.DAY,
        limit_price=round(entry_price, 2),
    )
    if use_bracket:
        params["order_class"] = OrderClass.BRACKET
        params["stop_loss"]   = {"stop_price": stop_price}
        params["take_profit"] = {"limit_price": target_price}

    try:
        order = _get_client().submit_order(LimitOrderRequest(**params))
        print(f"[ORDER] {direction.upper()} {symbol} x{qty} limit ${entry_price:.2f} "
              f"| stop ${stop_price:.2f} | target ${target_price:.2f} | id {order.id}")
        return str(order.id)
    except Exception as e:
        print(f"[ORDER] Failed to place equity order for {symbol}: {e}")
        return None


def place_option_order(
    symbol: str,
    direction: str,
    entry_price: float,
    qty: int = 1,
    expiration: date | None = None,
) -> str | None:
    """
    Buy an ATM call (breakout) or put (breakdown) expiring on the next Friday.
    Queries Alpaca for available contracts and picks the nearest strike to entry_price.
    Returns the Alpaca order ID, or None on failure.

    direction: 'breakout' → call | 'breakdown' → put
    """
    if not ALPACA_PAPER_KEY or not ALPACA_PAPER_SECRET:
        print("[OPTION] ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET not set — skipping.")
        return None

    exp     = expiration or _next_friday()
    ct      = ContractType.CALL if direction == "breakout" else ContractType.PUT
    ct_str  = "CALL" if direction == "breakout" else "PUT"

    try:
        client    = _get_client()
        contracts = client.get_option_contracts(
            GetOptionContractsRequest(
                underlying_symbols=[symbol],
                expiration_date=exp.isoformat(),
                type=ct,
                strike_price_gte=str(round(entry_price * 0.90, 2)),
                strike_price_lte=str(round(entry_price * 1.10, 2)),
            )
        )
    except Exception as e:
        print(f"[OPTION] Failed to fetch contracts for {symbol}: {e}")
        return None

    if not contracts:
        print(f"[OPTION] No {ct_str} contracts found for {symbol} exp {exp} near ${entry_price:.2f}")
        return None

    # Nearest ATM strike
    contract = min(contracts, key=lambda c: abs(float(c.strike_price) - entry_price))
    print(f"[OPTION] Selected {ct_str} {contract.symbol} strike ${contract.strike_price} exp {exp}")

    try:
        order = client.submit_order(
            MarketOrderRequest(
                symbol=contract.symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        )
        print(f"[OPTION] Order placed: {contract.symbol} x{qty} | id {order.id}")
        return str(order.id)
    except Exception as e:
        print(f"[OPTION] Failed to place option order for {contract.symbol}: {e}")
        return None
