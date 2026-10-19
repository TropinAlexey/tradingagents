"""Durable lifecycle of the protective exits attached to a futures entry."""

from __future__ import annotations

import hashlib
import math
import threading
from datetime import datetime, timezone
from typing import Any

import ccxt

from server import job_store
from tradingagents.execution.sizing import PlannedOrder

_TASK_LOCK = threading.RLock()
_TERMINAL_STATUSES = {
    "emergency_closed", "reconciled_take_profit",
    "reconciled_stop_loss", "cancelled", "completed",
}


def _venue_key(bridge: Any) -> str:
    config = bridge.config
    return "|".join((
        str(bridge.exchange_id).lower(),
        str(config.get("exec_base_url") or "").rstrip("/").lower(),
        str(config.get("exec_sandbox") is True),
    ))


def _info(item: dict) -> dict:
    value = item.get("info")
    return value if isinstance(value, dict) else item


def _order_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    value = item.get("id") or _info(item).get("algoId")
    return str(value) if value else None


def _state(item: dict) -> str | None:
    info = _info(item)
    raw = str(info.get("algoStatus") or item.get("status") or "").upper()
    if raw in {"FINISHED", "FILLED"}:
        return "filled"
    if raw == "CLOSED" and not info.get("algoStatus"):
        return "filled"
    if raw in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}:
        return "cancelled"
    if raw in {"NEW", "ACCEPTED", "TRIGGERING", "TRIGGERED", "PARTIALLY_FILLED", "OPEN"}:
        return "placed"
    return None


def _same_number(expected: Any, actual: Any) -> bool:
    try:
        left, right = float(expected), float(actual)
    except (TypeError, ValueError):
        return False
    return math.isfinite(left) and math.isfinite(right) and math.isclose(
        left, right, rel_tol=1e-9, abs_tol=1e-12,
    )


def _matches(item: dict, task: dict, leg: dict) -> bool:
    item_id = _order_id(item)
    if not item_id:
        return False
    if leg.get("order_id"):
        return item_id == str(leg["order_id"])
    info = _info(item)
    if item.get("symbol") and item["symbol"] != task["symbol"]:
        return False
    if not item.get("symbol"):
        raw_symbol = task["symbol"].split(":", 1)[0].replace("/", "")
        if info.get("symbol") != raw_symbol:
            return False
    if str(info.get("side") or item.get("side") or "").lower() != task["close_side"]:
        return False
    if str(info.get("reduceOnly", item.get("reduceOnly"))).lower() not in {"true", "1"}:
        return False
    expected_type = "STOP_MARKET" if leg["name"] == "stop-loss" else "TAKE_PROFIT_MARKET"
    actual_type = str(info.get("orderType") or info.get("origType") or item.get("type") or "").upper()
    if expected_type != actual_type:
        return False
    quantity = info.get("quantity", item.get("amount"))
    trigger = info.get("triggerPrice") or info.get("stopPrice") or item.get("triggerPrice")
    price = leg["params"].get("stopLossPrice", leg["params"].get("takeProfitPrice"))
    return _same_number(task["quantity"], quantity) and _same_number(price, trigger)


def _cancel_confirmed(response: Any, order_id: str) -> bool:
    if not isinstance(response, dict) or _order_id(response) != order_id:
        return False
    if _state(response) == "cancelled":
        return True
    info = _info(response)
    return str(info.get("code")) == "200" and info.get("msg") == "success"


class BracketManager:
    """Protective-exit persistence and reconciliation, without an entry-order path."""

    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    @property
    def _trigger_params(self) -> dict:
        return {"trigger": True} if self.bridge.exchange_id == "binance" else {}

    def _save(self, task: dict, status: str, error: str | None = None) -> str:
        ids = [str(leg["order_id"]) for leg in task["legs"] if leg.get("order_id")]
        job_store.update_bracket_recovery(
            task["task_id"], status=status, placed_ids=ids, attempts=task["attempts"],
            last_error=self.bridge._redact(error) if error else None,
            now=datetime.now(timezone.utc).isoformat(), legs=task["legs"],
        )
        return status

    def place(self, order: PlannedOrder, confirm: bool, entry_order_id: str | None) -> None:
        close_side = "sell" if order.side == "buy" else "buy"
        legs = [
            {"name": name, "params": {param: value}, "status": "pending", "order_id": None}
            for name, param, value in (
                ("stop-loss", "stopLossPrice", order.stop_loss),
                ("take-profit", "takeProfitPrice", order.take_profit),
            ) if value is not None
        ]
        if not legs:
            return
        task_id = f"bracket:{order.ccxt_symbol}:{entry_order_id or 'unknown'}"
        with _TASK_LOCK:
            job_store.create_bracket_recovery(
                task_id, symbol=order.ccxt_symbol, entry_order_id=entry_order_id or "unknown",
                close_side=close_side, quantity=float(order.quantity), legs=legs,
                now=datetime.now(timezone.utc).isoformat(), venue_key=_venue_key(self.bridge),
            )
            task = job_store.load_bracket_recovery(task_id)
            exchange = self.bridge.client()
            try:
                for leg in task["legs"]:
                    if leg["status"] != "pending":
                        continue
                    response = exchange.create_order(
                        task["symbol"], "market", close_side, task["quantity"],
                        None, {**leg["params"], "reduceOnly": True},
                    )
                    leg_id = _order_id(response)
                    if not leg_id:
                        raise RuntimeError(f"{leg['name']} conditional order returned no id")
                    leg.update(status="placed", order_id=leg_id)
                    self._save(task, "pending")
            except ccxt.NetworkError as exc:
                for leg in task["legs"]:
                    if leg["status"] == "pending":
                        leg["status"] = "uncertain"
                self._save(task, "submission_uncertain", f"conditional submission uncertain; inspect before retry: {exc!r}")
                self.bridge.audit_plan(
                    order, action="bracket_failed", confirmed=confirm, order_id=entry_order_id,
                    reason=f"protective exits need inspection after uncertain submit; recovery task {task_id}",
                    phase="execute",
                )
                return
            except Exception as exc:  # the entry already exists on the venue
                self._save(task, "pending", repr(exc))
                self.bridge.audit_plan(
                    order, action="bracket_failed", confirmed=confirm, order_id=entry_order_id,
                    reason=f"protective exits failed after entry fill; recovery task {task_id}: {exc!r}",
                    phase="execute",
                )
                return
            self._save(task, "monitoring")
            self.bridge.audit_plan(
                order, action="bracket_placed", confirmed=confirm,
                order_id=",".join(str(leg["order_id"]) for leg in task["legs"]),
                reason="exchange-side conditional stopLoss/takeProfit attached after derivatives fill",
                phase="execute",
            )

    def reconcile(self, task_id: str, *, repair_missing: bool, allow_sibling_cancel: bool) -> str:
        with _TASK_LOCK:
            task = job_store.load_bracket_recovery(task_id)
            if task is None:
                raise KeyError(task_id)
            if task["status"] in _TERMINAL_STATUSES:
                return task["status"]
            if task.get("venue_key") and task["venue_key"] != _venue_key(self.bridge):
                self._save(task, task["status"], "configured venue/profile does not match the venue that placed this bracket")
                return "venue_mismatch"
            exchange = self.bridge.client()
            try:
                existing = exchange.fetch_open_orders(task["symbol"], params=self._trigger_params)
                if not isinstance(existing, list):
                    raise ValueError("conditional order list is invalid")
            except Exception as exc:
                self._save(task, task["status"], f"conditional order inspection failed: {exc!r}")
                return "inspection_failed"
            errors = self._inspect(exchange, task, existing)
            if errors:
                self._save(task, task["status"], "; ".join(errors))
                return "reconcile_incomplete"
            if task["status"] == "submission_uncertain":
                for leg in task["legs"]:
                    if leg["status"] == "uncertain" and leg.get("order_id"):
                        leg["status"] = "placed"
                task["status"] = "pending"
            filled = [leg for leg in task["legs"] if leg["status"] == "filled"]
            if filled:
                return self._cleanup(exchange, task, filled[0], allow_sibling_cancel)
            if all(leg["status"] == "cancelled" for leg in task["legs"]):
                return self._save(task, "cancelled")
            if any(leg["status"] == "cancelled" for leg in task["legs"]):
                return self._save(task, "monitoring", "conditional leg canceled without a confirmed fill")
            if repair_missing and any(leg["status"] == "pending" for leg in task["legs"]):
                return self._repair(exchange, task)
            return self._save(task, task["status"] if task["status"] == "pending" else "monitoring")

    def _inspect(self, exchange: Any, task: dict, existing: list) -> list[str]:
        observed = {_order_id(item): item for item in existing if isinstance(item, dict) and _order_id(item)}
        errors = []
        for leg in task["legs"]:
            if leg["status"] in {"filled", "cancelled"}:
                continue
            if leg["status"] == "uncertain":
                if not leg.get("order_id"):
                    candidates = [item for item in existing if isinstance(item, dict) and _matches(item, task, leg)]
                    if len(candidates) != 1:
                        errors.append(f"uncertain {leg['name']} conditional submission")
                        continue
                    leg["order_id"] = _order_id(candidates[0])
                    leg["status"] = "placed"
                else:
                    leg["status"] = "placed"
            if not leg.get("order_id"):
                candidates = [item for item in observed.values() if _matches(item, task, leg)]
                if len(candidates) > 1:
                    errors.append(f"ambiguous {leg['name']} conditional orders")
                    continue
                if candidates:
                    leg["order_id"] = _order_id(candidates[0])
            order_id = leg.get("order_id")
            if not order_id:
                continue
            try:
                item = observed.get(order_id)
                if item is None:
                    item = exchange.fetch_order(order_id, task["symbol"], params=self._trigger_params)
                if _order_id(item) != order_id or _state(item) is None:
                    raise ValueError(f"unconfirmed status for conditional order {order_id}")
                leg["status"] = _state(item)
            except Exception as exc:
                errors.append(f"{order_id}: {exc!r}")
        return errors

    def _cleanup(self, exchange: Any, task: dict, winner: dict, allow_cancel: bool) -> str:
        errors = []
        for leg in task["legs"]:
            if leg is winner or leg["status"] in {"filled", "cancelled"}:
                continue
            if leg["status"] == "pending" and not leg.get("order_id"):
                leg["status"] = "cancelled"
                continue
            if not allow_cancel:
                errors.append("sibling cancellation is gated off")
                continue
            try:
                response = exchange.cancel_order(leg["order_id"], task["symbol"], params=self._trigger_params)
                if not _cancel_confirmed(response, leg["order_id"]):
                    raise ValueError("conditional cancel returned unconfirmed status")
                leg["status"] = "cancelled"
                self._save(task, "monitoring")
            except Exception as exc:
                errors.append(f"cancel {leg['order_id']}: {exc!r}")
        if errors:
            self._save(task, "monitoring", "; ".join(errors))
            return "reconcile_incomplete"
        return self._save(task, f"reconciled_{winner['name'].replace('-', '_')}")

    def _repair(self, exchange: Any, task: dict) -> str:
        task["attempts"] += 1
        try:
            for leg in task["legs"]:
                if leg["status"] != "pending":
                    continue
                response = exchange.create_order(
                    task["symbol"], "market", task["close_side"], task["quantity"],
                    None, {**leg["params"], "reduceOnly": True},
                )
                leg_id = _order_id(response)
                if not leg_id:
                    raise RuntimeError(f"{leg['name']} conditional order returned no id")
                leg.update(status="placed", order_id=leg_id)
                self._save(task, "pending")
        except ccxt.NetworkError as exc:
            for leg in task["legs"]:
                if leg["status"] == "pending":
                    leg["status"] = "uncertain"
            self._save(task, "submission_uncertain", f"protective submission is uncertain; inspect before retry: {exc!r}")
            return "reconcile_incomplete"
        except Exception as exc:
            return self._emergency_close(exchange, task, exc)
        return self._save(task, "monitoring")

    def _cancel_resting_legs(self, exchange: Any, task: dict, allow_cancel: bool) -> str:
        errors = []
        for leg in task["legs"]:
            if leg["status"] in {"filled", "cancelled"}:
                continue
            order_id = leg.get("order_id")
            if not order_id:
                if leg["status"] == "pending":
                    leg["status"] = "cancelled"
                else:
                    errors.append(f"{leg['name']} conditional order id is unknown")
                continue
            if not allow_cancel:
                errors.append("conditional cleanup is gated off")
                continue
            try:
                response = exchange.cancel_order(
                    order_id, task["symbol"], params=self._trigger_params
                )
                if not _cancel_confirmed(response, order_id):
                    raise ValueError("conditional cancel returned unconfirmed status")
                leg["status"] = "cancelled"
            except Exception as exc:
                errors.append(f"cancel {order_id}: {exc!r}")
        if errors:
            return self._save(task, "emergency_cleanup_pending", "; ".join(errors))
        return self._save(task, "emergency_closed")

    def _emergency_close(self, exchange: Any, task: dict, error: Exception) -> str:
        client_order_id = "emergency-" + hashlib.sha256(task["task_id"].encode()).hexdigest()[:20]
        try:
            response = exchange.create_order(
                task["symbol"], "market", task["close_side"], task["quantity"],
                None, {"reduceOnly": True, "clientOrderId": client_order_id},
            )
            if not isinstance(response, dict) or _state(response) != "filled":
                raise ValueError("emergency close was not confirmed filled")
        except Exception as exc:
            return self._save(task, "emergency_close_failed", f"protective recovery failed: {error!r}; emergency close failed: {exc!r}")
        return self._cancel_resting_legs(exchange, task, allow_cancel=True)
