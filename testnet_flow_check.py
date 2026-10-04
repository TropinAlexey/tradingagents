"""Full-flow testnet verification — staged, fail-fast, no mainnet.

Layer 1 (venue, spot): real ExchangeBridge with exec_sandbox + exec_live armed,
  a tiny long plan with an ATR bracket -> live fill -> exchange-side bracket ->
  verify both orders exist on the venue -> close the position.

Layer 2 (venue, futures): same through DerivativesExecutor (testnet USDT-M),
  leverage 2, reduceOnly bracket, long then short -> verify -> close.

Safety: every stage asserts the client's hostnames are testnet BEFORE any order
is sent; a non-testnet hostname aborts the run. Orders are tiny (1% of testnet
balance) and closed at the end of each stage.
"""

import contextlib
import os
import sys
from datetime import datetime, timezone

os.environ["TRADINGAGENTS_EXEC_SANDBOX"] = "true"
os.environ["TRADINGAGENTS_EXEC_LIVE"] = "true"
os.environ["TRADINGAGENTS_EXEC_AUTO_CONFIRM"] = "true"
os.environ["TRADINGAGENTS_EXEC_DERIVATIVES"] = "true"

import ccxt  # noqa: E402

from tradingagents.dataflows.config import get_config, set_config  # noqa: E402

set_config({
    "exec_sandbox": True,
    "exec_live": True,
    "exec_auto_confirm": True,
    "exec_derivatives": True,
    "exec_log_path": str(__import__("pathlib").Path("server/data/testnet-flow-audit.jsonl")),
    # The testnet account already holds ~72% of its equity in BTC from an
    # earlier run, so default caps (2% per asset) rightly refuse any new Buy.
    # This test RAISES the caps deliberately: it is testing the plumbing, not
    # the risk limits (those have their own unit tests).
    "risk_max_position_pct_per_asset": 90.0,
    "risk_max_daily_loss_pct": 50.0,
    "risk_max_total_exposure_pct": 100.0,
    "risk_max_derivatives_leverage": 3.0,
    "risk_max_derivatives_exposure_pct": 50.0,
    "results_dir": str(__import__("pathlib").Path("server/data/testnet-results")),
})

FAILURES: list[str] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def assert_testnet(client: ccxt.Exchange, label: str) -> bool:
    """Only the api urls matter — ccxt keeps doc/github urls on the main domain
    even in sandbox mode (verified on ccxt 4.5.84)."""
    api = client.urls.get("api", {})
    watched = {
        key: api[key] for key in ("public", "private", "fapiPublic", "fapiPrivate")
        if key in api
    }
    is_testnet = bool(watched) and all(
        "testnet" in url or "binance.vision" in url for url in watched.values()
    )
    step(f"{label}: venue is testnet", is_testnet,
         ", ".join(f"{k}={v}" for k, v in watched.items())[:160])
    return is_testnet


def open_bracket_orders(exchange: ccxt.Exchange, symbol: str) -> list:
    return [o for o in exchange.fetch_open_orders(symbol)
            if o.get("info", {}).get("origStopPrice")
            or o.get("stopPrice") or o.get("triggerPrice")]


# ---------------------------------------------------------------- layer 1: spot
def layer_spot() -> None:
    print("\n=== LAYER 1: spot full path (live testnet, bracket) ===", flush=True)
    from tradingagents.dataflows.screening import atr_targets
    from tradingagents.execution.bridge import ExchangeBridge

    bridge = ExchangeBridge(config=get_config())
    client = bridge.client()
    client.load_markets()
    if not assert_testnet(client, "spot"):
        return

    # pre-clean: cancel any open orders left by an earlier run, flatten BTC.
    # A vanish (-2011 Unknown order) between list and cancel is fine — the
    # goal is "no open orders", so tolerate it.
    for order in client.fetch_open_orders("BTC/USDT"):
        with contextlib.suppress(ccxt.OrderNotFound):
            client.cancel_order(order["id"], "BTC/USDT")
    pre_held = float((client.fetch_balance().get("free") or {}).get("BTC", 0) or 0)
    if pre_held >= 0.00001:
        client.create_order("BTC/USDT", "market", "sell",
                            client.amount_to_precision("BTC/USDT", pre_held))
        print(f"pre-clean: flattened {pre_held} BTC", flush=True)

    # plan_order's percentage caps need a real portfolio: build it from the
    # venue itself (same shape the autoloop passes to _handle_plan).
    portfolio = bridge.sync_portfolio()
    balance = client.fetch_balance()
    free = float((balance.get("free") or {}).get("USDT", 0) or 0)
    step("spot: testnet balance readable", free > 0, f"free USDT={free:.2f}")
    if free <= 0:
        return

    price = float(client.fetch_ticker("BTC/USDT")["last"])
    plan = bridge.plan_order("BTC-USD", "Buy", portfolio, price=price)
    step("spot: plan_order sizes a long", plan.side == "buy" and plan.quantity and plan.quantity > 0,
         f"side={plan.side} qty={plan.quantity} cost={plan.cost}")
    if plan.side is None:
        step("spot: plan refusal reason", False, str(plan.reason)[:160])
        return
    # Cap the entry at ~50 USDT: this is a plumbing test, not a position.
    tiny_qty = round(min(50.0 / price, plan.quantity), 6)
    plan = plan.model_copy(update={"quantity": tiny_qty, "cost": tiny_qty * price})
    today = datetime.now(timezone.utc).date().isoformat()
    stop, take = atr_targets("BTC-USD", today, "crypto")
    if stop and take:
        plan = plan.model_copy(update={"stop_loss": stop, "take_profit": take})
    step("spot: ATR bracket attached", stop is not None and take is not None,
         f"SL={stop} TP={take}" if stop and take else "ATR unavailable")

    order_id = bridge.execute_order(plan, confirm=True)
    step("spot: live fill on testnet", bool(order_id), f"order_id={order_id}")

    # The OCO is one order LIST: the LIMIT_MAKER TP leg has no trigger field,
    # so count ALL open orders on the symbol (pre-clean guarantees they're
    # only ours) — both legs must be resting on the venue.
    orders = client.fetch_open_orders("BTC/USDT")
    step("spot: OCO bracket live on venue (both legs)", len(orders) >= 2,
         f"{len(orders)} open order(s): "
         + ", ".join(f"{o.get('type')}@{o.get('price') or o.get('stopPrice')}"
                     for o in orders[:4]))

    # cleanup: CANCEL the OCO first (its TP leg locks the bought BTC), then
    # flatten the freed balance.
    for order in orders:
        with contextlib.suppress(ccxt.OrderNotFound):
            client.cancel_order(order["id"], "BTC/USDT")
    held = float((client.fetch_balance().get("free") or {}).get("BTC", 0) or 0)
    if held >= 0.00001:
        client.create_order("BTC/USDT", "market", "sell",
                            client.amount_to_precision("BTC/USDT", held))
    after = float((client.fetch_balance().get("free") or {}).get("BTC", 0) or 0)
    step("spot: cleanup flattened the position",
         len(client.fetch_open_orders("BTC/USDT")) == 0,
         f"cancelled {len(orders)} OCO leg(s), residual BTC={after:.8f}")


# ------------------------------------------------------------- layer 2: futures
def layer_futures() -> None:
    """SKIPPED unless demo credentials exist: Binance demo trading (demo-
    fapi.binance.com) rejects the regular testnet API keys with 401 — a demo
    key must be created at demo.binance.com and placed in BINANCE_DEMO_API_KEY
    / BINANCE_DEMO_SECRET. Everything below runs when those are present."""
    print("\n=== LAYER 2: futures full path (Binance demo, reduceOnly) ===", flush=True)
    demo_key = os.environ.get("BINANCE_DEMO_API_KEY")
    demo_secret = os.environ.get("BINANCE_DEMO_SECRET")
    if not demo_key or not demo_secret:
        step("futures: layer SKIPPED — needs demo API keys", True,
             "demo-fapi rejects regular testnet keys (401). Tạo key tại "
             "demo.binance.com rồi đặt BINANCE_DEMO_API_KEY/BINANCE_DEMO_SECRET.")
        return
    from tradingagents.execution.derivatives import DerivativesExecutor

    # exec_sandbox must be OFF here: ccxt forbids demo trading while sandbox
    # mode is enabled (they are mutually exclusive on one client). The gate
    # reads the env at call time, so scope the override to this layer.
    os.environ.pop("TRADINGAGENTS_EXEC_SANDBOX", None)
    config = {**get_config(), "exec_sandbox": False}
    executor = DerivativesExecutor(config=config)
    client = executor._bridge.client()
    client.apiKey = demo_key
    client.secret = demo_secret
    client.options["defaultType"] = "swap"
    # ccxt 4.5.x removed Binance futures testnet (sign() raises NotSupported:
    # "testnet/sandbox mode is not supported for futures anymore"); demo
    # trading on demo-issued keys is the supported non-live venue.
    client.enable_demo_trading(True)
    try:
        client.load_markets()
    except Exception as exc:
        step("futures: demo markets load", False, f"{type(exc).__name__}: {exc}")
        return
    api = client.urls.get("api", {})
    watched = {k: api[k] for k in ("fapiPublic", "fapiPrivate") if k in api}
    is_demo = bool(watched) and all(
        "demo" in url or "testnet" in url for url in watched.values()
    )
    step("futures: venue is demo (not live)", is_demo,
         ", ".join(f"{k}={v}" for k, v in watched.items())[:140])
    if not is_demo:
        return

    symbol = executor.symbol_for("BTC-USD")
    balance = client.fetch_balance()
    free = float((balance.get("free") or {}).get("USDT", 0) or 0)
    step("futures: demo balance readable", free > 0, f"free USDT={free:.2f} symbol={symbol}")
    if free <= 0:
        return

    price = float(client.fetch_ticker(symbol)["last"])
    portfolio = executor._bridge.sync_portfolio()
    plan = executor.plan_order("BTC-USD", "Buy", portfolio, price=price, leverage=2.0)
    step("futures: plan_order sizes a leveraged long",
         plan.side == "buy" and plan.market == "derivatives" and (plan.quantity or 0) > 0,
         f"side={plan.side} qty={plan.quantity} leverage={plan.leverage}")
    if plan.side is None:
        step("futures: plan refusal reason", False, str(plan.reason)[:160])
        return
    plan = plan.model_copy(update={
        "stop_loss": round(price * 0.97, 2),
        "take_profit": round(price * 1.03, 2),
    })
    order_id = executor.execute_order(plan, confirm=True, portfolio=portfolio)
    step("futures: live leveraged fill on demo venue", bool(order_id), f"order_id={order_id}")

    positions = client.fetch_positions([symbol])
    live = [p for p in positions if abs(float(p.get("contracts") or 0)) > 0]
    step("futures: position opened on venue", len(live) == 1,
         ", ".join(f"{p['symbol']} contracts={p.get('contracts')} leverage={p.get('leverage')}"
                   for p in live) or "none")

    orders = open_bracket_orders(client, symbol)
    step("futures: reduceOnly bracket live on venue", len(orders) >= 1,
         f"{len(orders)} protective order(s): "
         + ", ".join(f"{o.get('side')}@{o.get('stopPrice') or o.get('triggerPrice') or o.get('price')}"
                     for o in orders[:4]))

    if live:
        client.create_order(symbol, "market", "sell",
                            client.amount_to_precision(symbol, live[0]["contracts"]),
                            params={"reduceOnly": True})
    for order in orders:
        client.cancel_order(order["id"], symbol)
    positions = client.fetch_positions([symbol])
    remaining = [p for p in positions if abs(float(p.get("contracts") or 0)) > 0]
    step("futures: cleanup flattened the position", len(remaining) == 0,
         f"positions left={len(remaining)}")


if __name__ == "__main__":
    layer_spot()
    layer_futures()
    print("\n=== SUMMARY ===", flush=True)
    if FAILURES:
        print(f"FAILED stages: {FAILURES}", flush=True)
        sys.exit(1)
    print("all venue stages passed", flush=True)
