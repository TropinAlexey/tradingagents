"""Performance: GET /api/performance (docs/ui-api-contract.md §0 conventions).

One concern: trade-performance metrics replayed from the engine's execution
audit log (``exec_log_path``). Fills are buy/sell lines with
``phase="execute"`` and usable qty/price_est — plan lines, risk rejections
and awaiting-approval lines never move a position. Long-only FIFO per
ticker: every buy lot a sell matches is one closed round-trip whose return
is ``(sell / buy - 1) * 100``. The read goes through ``audit.read_events``
so an unreadable log answers 503 ``audit_log_unreadable`` exactly like
/api/audit and /api/portfolio; a missing or empty log is the all-zero empty
state, never an error. Open-position marks come through the
``price_fetcher`` seam so tests inject fakes and nothing touches the venue.
"""

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter

from server import audit as audit_log
from server.contract import utc_now_iso
from tradingagents.dataflows.config import get_config

router = APIRouter(prefix="/api", tags=["performance"])

RECENT_ORDERS_LIMIT = 50  # newest execute lines the board shows

_QTY_EPSILON = 1e-12  # mirrors risk.py's tolerance for float leftovers

# Lazy venue behind the default mark. Kept between requests and rebuilt when
# the configured venue changes, so a settings PUT to exec_exchange_id never
# leaves marks coming from the old exchange.
_default_bridge = None
_default_bridge_venue: tuple[str, bool] | None = None


@dataclass
class _OpenLot:
    """One unmatched buy fill; FIFO leftovers are reported per lot."""

    ticker: str
    qty: float
    price: float
    mode: str | None
    entry_at: str | None


def _default_price_fetcher(ticker: str) -> float | None:
    """Default mark for open positions: a lazily built ExchangeBridge.

    Any failure — venue not buildable, exchange unreachable, ticker outside
    the executable set — degrades to None: marks are cosmetic on the board
    and must never fail the response. Tests monkeypatch this module
    attribute with a fake, so the default never runs there.
    """
    global _default_bridge, _default_bridge_venue
    try:
        config = get_config()
        venue = (str(config.get("exec_exchange_id")), config.get("exec_sandbox") is True)
        if _default_bridge is None or _default_bridge_venue != venue:
            from tradingagents.execution.bridge import ExchangeBridge

            _default_bridge = ExchangeBridge(config=config)
            _default_bridge_venue = venue
        return _default_bridge.fetch_price(ticker)
    except Exception:  # venue-side failures degrade to "no mark"
        return None


def _is_fill(event: dict) -> bool:
    """A position-moving fill: buy/sell executed with a real ticker and
    usable qty/price (a zero or negative value cannot form a round-trip)."""
    if event.get("action") not in ("buy", "sell") or event.get("phase") != "execute":
        return False
    if not isinstance(event.get("ticker"), str) or not event["ticker"]:
        return False
    try:
        return float(event.get("qty")) > 0 and float(event.get("price_est")) > 0
    except (TypeError, ValueError):
        return False


def _replay_fills(fills: list[dict]) -> tuple[list[float], list[_OpenLot]]:
    """Long-only FIFO per ticker.

    A buy opens a lot, a sell closes lots oldest first, and every lot-match
    is one closed round-trip whose return is ``(sell / buy - 1) * 100``. A
    sell with no open lot has no basis in a long-only book and is dropped —
    the same stance as risk.py's unknown-basis closes. Returns the closed
    round-trip returns (in close order) and the open lots in entry order.
    """
    open_lots: dict[str, deque[_OpenLot]] = defaultdict(deque)
    closed_pnls: list[float] = []
    for event in fills:
        ticker = event["ticker"]
        qty, price = float(event["qty"]), float(event["price_est"])
        if event["action"] == "buy":
            open_lots[ticker].append(_OpenLot(
                ticker=ticker, qty=qty, price=price,
                mode=event.get("mode"), entry_at=event.get("timestamp"),
            ))
            continue
        remaining = qty
        while remaining > _QTY_EPSILON and open_lots[ticker]:
            lot = open_lots[ticker][0]
            matched = min(lot.qty, remaining)
            closed_pnls.append((price / lot.price - 1) * 100)
            lot.qty -= matched
            remaining -= matched
            if lot.qty <= _QTY_EPSILON:
                open_lots[ticker].popleft()
    return closed_pnls, [lot for lots in open_lots.values() for lot in lots]


def _summarize(closed_pnls: list[float]) -> dict:
    """Win/loss arithmetic over closed round-trip returns. Losses (pnl <= 0)
    keep their sign, so win_rate * avg_win + loss_rate * avg_loss == expectancy."""
    closed = len(closed_pnls)
    wins = [pnl for pnl in closed_pnls if pnl > 0]
    losses = [pnl for pnl in closed_pnls if pnl <= 0]
    return {
        "closed_trades": closed,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / closed * 100 if closed else 0.0,
        "avg_win_pct": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss_pct": sum(losses) / len(losses) if losses else 0.0,
        "expectancy_pct": sum(closed_pnls) / closed if closed else 0.0,
    }


def _open_position_rows(
    open_lots: list[_OpenLot], fetch: Callable[[str], float | None]
) -> list[dict]:
    """One row per unmatched buy lot, marked through the price seam (each
    ticker is fetched once per call)."""
    marks: dict[str, float | None] = {}
    rows: list[dict] = []
    for lot in open_lots:
        if lot.ticker not in marks:
            marks[lot.ticker] = fetch(lot.ticker)
        current = marks[lot.ticker]
        rows.append({
            "ticker": lot.ticker,
            "qty": lot.qty,
            "entry_price": lot.price,
            "current_price": current,
            "unrealized_pct": (current / lot.price - 1) * 100 if current is not None else None,
            "mode": lot.mode,
            "entry_at": lot.entry_at,
        })
    return rows


def _bracket_counts(events: list[dict]) -> dict:
    """Protective-exit health: exchange-side bracket placements vs failures."""
    return {
        "placed": sum(1 for event in events if event.get("action") == "bracket_placed"),
        "failed": sum(1 for event in events if event.get("action") == "bracket_failed"),
    }


def _recent_orders(events: list[dict]) -> list[dict]:
    """The newest execute-phase audit lines, newest first, capped. The row
    shape is explicit so read_events' ``_line_no`` provenance never leaks."""
    execute_lines = [
        event for event in events if event.get("phase") == "execute" and event.get("action")
    ]
    recent = execute_lines[-RECENT_ORDERS_LIMIT:]
    recent.reverse()
    return [{
        "timestamp": event.get("timestamp"),
        "ticker": event.get("ticker"),
        "action": event.get("action"),
        "qty": event.get("qty"),
        "price_est": event.get("price_est"),
        "mode": event.get("mode"),
        "order_id": event.get("order_id"),
    } for event in recent]


def compute_performance(
    events: list[dict], price_fetcher: Callable[[str], float | None] | None = None
) -> dict:
    """The performance payload from raw audit events; the router adds generated_at.

    ``price_fetcher`` marks open positions (ticker -> last price or None);
    None selects the module's lazy ExchangeBridge default
    (_default_price_fetcher). Tests inject a fake so nothing touches the network.
    """
    closed_pnls, open_lots = _replay_fills([event for event in events if _is_fill(event)])
    fetch = price_fetcher if price_fetcher is not None else _default_price_fetcher
    return {
        "summary": _summarize(closed_pnls),
        "open_positions": _open_position_rows(open_lots, fetch),
        "brackets": _bracket_counts(events),
        "recent_orders": _recent_orders(events),
    }


@router.get("/performance")
def get_performance():
    events, _skipped = audit_log.read_events()  # 503 when the log exists but cannot be read
    return {"generated_at": utc_now_iso(), **compute_performance(events)}
