"""Autoloop: the scheduled trading cycle + the kill-switch halt endpoints.

One concern: run the engine's own once-a-day cycle on a timer (plus run-now)
and stop everything on demand. The cycle mirrors server/daily.py's auto scan
(screen a universe, run the LLM pipeline on the top candidates) but resolves
every plan through the engine's own confirm policy — ``_handle_plan`` from
``tradingagents/execution/daily.py``: auto-confirm DRY only when the config
``exec_auto_confirm`` literal AND the ``TRADINGAGENTS_EXEC_AUTO_CONFIRM`` env
flag read true at call time, LIVE additionally requires the FR5 double gate.
This cycle NEVER executes outside that policy, and a plan it does not
execute is only audited (the approval queue belongs to the daily-job
surface). Enabling the loop through the API is fail-closed behind the same
config+env gates: ``409 gate_closed`` — the UI can never arm an unattended
loop the engine's policy itself would refuse.

The kill switch is deliberately ungated: ``POST /api/halt`` appends a
``{"event": "halt"}`` line to the shared execution audit log, which the
RiskGuard of EVERY process replays — the rest of today is refused everywhere
until a reset or the UTC day rolls over (risk.py:163-173). Disabling the
loop is likewise never gated: turning a thing off is the safe direction.

State: ``enabled``/``interval_minutes`` persist in ``paths.AUTOLOOP_PATH``
(the scheduler re-reads the file every wake, so edits need no restart);
``last_cycle`` is an in-memory summary of the most recent cycle only.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from server import audit as audit_log, daily as daily_mod, paths, runs as runs_mod
from server.contract import ApiError, json_body, utc_now_iso
from tradingagents.agents.rating import RATINGS_5_TIER
from tradingagents.dataflows.config import get_config
from tradingagents.default_config import _BOOL_TRUE
from tradingagents.execution.audit import append_event
from tradingagents.execution.daily import DailyResult, _handle_plan

router = APIRouter(prefix="/api", tags=["autoloop"])

# Auto-cycle tuning: how many universe entries to pull per market and how
# many screened candidates graduate into the expensive LLM pipeline.
AUTO_UNIVERSE_PER_ASSET = 12
AUTO_TOP_N = 3

MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 1440
DEFAULT_INTERVAL_MINUTES = 1440

# Hard system ceiling on the leverage an auto cycle may REQUEST from the
# derivatives path, regardless of the configured risk cap. The RiskGuard's
# own ``risk_max_derivatives_leverage`` stays the authoritative gate (it can
# still refuse below this); this constant only bounds what the cycle asks for.
MAX_AUTO_LEVERAGE = 3.0

# Analyst sets per asset type, exactly like server/daily.py _analyze.
_ANALYSTS_CRYPTO = ("market", "social", "news")
_ANALYSTS_STOCK = ("market", "social", "news", "fundamentals")

logger = logging.getLogger(__name__)

# The 5-tier scale, unpacked like sizing.py/derivatives.py so the short-side
# mapping can never drift from the rating vocabulary.
_BUY, _OVERWEIGHT, _HOLD, _UNDERWEIGHT, _SELL = RATINGS_5_TIER

# One cycle at a time. The lock is held for the whole cycle; a concurrent
# spawn (scheduler tick + run-now) loses the acquire and is a silent no-op.
_cycle_lock = threading.Lock()
_cycle_thread: threading.Thread | None = None  # last spawned cycle worker
_scheduler_thread: threading.Thread | None = None
_wakeup = threading.Event()  # set on every state write so the loop re-reads at once
_last_cycle: dict | None = None


# --- gates ------------------------------------------------------------------


def _env_flag(name: str) -> bool:
    """Env gate read at call time, fail-closed.

    The exact read the engine's own policy does for both halves
    (execution/daily.py:67-76, bridge.py:592-603), so the UI's gate display
    can never disagree with what ``_handle_plan`` will decide.
    """
    raw = os.environ.get(name)
    if not raw:
        return False
    return raw.strip().lower() in _BOOL_TRUE


def gates() -> dict:
    """The confirm-policy gate state as GET /api/autoloop reports it.

    ``all_open`` (the enable precondition) is only the two auto-confirm
    halves: config literal True AND env true — matching ``_handle_plan``'s
    first two checks. The FR5 live halves and the FR-D derivatives halves are
    reported for observability but never unlock this API surface: live and
    futures remain the engine policy's decision.
    """
    config = get_config()
    auto_confirm_config = config.get("exec_auto_confirm") is True
    auto_confirm_env = _env_flag("TRADINGAGENTS_EXEC_AUTO_CONFIRM")
    return {
        "auto_confirm_config": auto_confirm_config,
        "auto_confirm_env": auto_confirm_env,
        "exec_live_config": config.get("exec_live") is True,
        "exec_live_env": _env_flag("TRADINGAGENTS_EXEC_LIVE"),
        "exec_derivatives_config": config.get("exec_derivatives") is True,
        "exec_derivatives_env": _env_flag("TRADINGAGENTS_EXEC_DERIVATIVES"),
        "all_open": auto_confirm_config and auto_confirm_env,
    }


# --- state file ---------------------------------------------------------------


def _load_state() -> dict:
    """The persisted {enabled, interval_minutes, updated_at}; defaults when
    missing or unreadable — a fresh install has the loop OFF, not an error."""
    path = paths.AUTOLOOP_PATH
    if not path.exists():
        return {"enabled": False, "interval_minutes": DEFAULT_INTERVAL_MINUTES}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("autoloop state file %s unreadable; treating as disabled", path)
        return {"enabled": False, "interval_minutes": DEFAULT_INTERVAL_MINUTES}
    return data if isinstance(data, dict) else {"enabled": False, "interval_minutes": DEFAULT_INTERVAL_MINUTES}


def _save_state(state: dict) -> None:
    paths.ensure_data_dir()
    tmp_path = paths.AUTOLOOP_PATH.with_name(paths.AUTOLOOP_PATH.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)
    tmp_path.replace(paths.AUTOLOOP_PATH)


def _interval_from(state: dict) -> int:
    raw = state.get("interval_minutes")
    if (
        isinstance(raw, bool)
        or not isinstance(raw, int)
        or not MIN_INTERVAL_MINUTES <= raw <= MAX_INTERVAL_MINUTES
    ):
        return DEFAULT_INTERVAL_MINUTES
    return raw


def _set_last_cycle(summary: dict) -> None:
    global _last_cycle
    _last_cycle = summary


# --- scheduler + cycle --------------------------------------------------------


def ensure_started() -> None:
    """Start the scheduler daemon once; idempotent — every enable calls it."""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, name="server-autoloop-scheduler", daemon=True
    )
    _scheduler_thread.start()


def _scheduler_loop() -> None:
    """Wait the configured interval (or until a state write wakes the loop),
    then re-read the state file and run one cycle if enabled. A changed
    interval or enabled flag therefore takes effect on the next wake."""
    while True:
        state = _load_state()
        _wakeup.wait(timeout=_interval_from(state) * 60.0)
        _wakeup.clear()
        if _load_state().get("enabled"):
            _spawn_cycle()


def _spawn_cycle(graph_builder: Callable | None = None) -> str:
    """Run one cycle on a worker thread unless one is already running."""
    global _cycle_thread
    if _cycle_lock.locked():
        return "already_running"
    thread = threading.Thread(
        target=_run_cycle_locked, args=(graph_builder,), name="server-autoloop-cycle",
        daemon=True,
    )
    _cycle_thread = thread
    thread.start()
    return "started"


def _run_cycle_locked(graph_builder: Callable | None = None) -> None:
    if not _cycle_lock.acquire(blocking=False):
        return  # a concurrent spawn won: it runs, this one is a no-op
    try:
        _run_cycle(graph_builder)
    finally:
        _cycle_lock.release()


def _run_cycle(graph_builder: Callable | None = None) -> list[DailyResult]:
    """One auto cycle: screen the universe, run the pipeline per candidate,
    hand every plan to the engine's confirm policy. Returns one DailyResult
    per candidate. A cycle requested while a run/job is active is skipped and
    audited (set_config is process-wide — trading_graph.py:65 — so the cycle
    must not fight another worker over config); a candidate's failure never
    stops the cycle (execution/daily.py:170-173)."""
    started_at = utc_now_iso()
    build_graph = graph_builder if graph_builder is not None else _default_graph_builder

    busy_run = runs_mod.active_run_id()
    busy_job = None if busy_run is not None else daily_mod.active_job_id()
    if busy_run is not None or busy_job is not None:
        occupied = f"run {busy_run}" if busy_run is not None else f"daily job {busy_job}"
        audit_log.record("autoloop_cycle_skipped", reason=f"another worker is active: {occupied}")
        _set_last_cycle({
            "started_at": started_at, "finished_at": utc_now_iso(),
            "status": "skipped_busy", "reason": occupied,
            "candidates": [], "results": [], "error": None,
        })
        return []

    audit_log.record("autoloop_cycle_started")
    config = get_config()  # snapshot: later settings changes do not touch this cycle
    summary: dict = {
        "started_at": started_at, "finished_at": None, "status": "completed",
        "candidates": [], "results": [], "error": None,
    }
    results: list[DailyResult] = []
    try:
        from tradingagents.dataflows.screening import (
            crypto_universe,
            screen_universe,
            stock_universe,
        )

        crypto = crypto_universe(config, AUTO_UNIVERSE_PER_ASSET)
        stocks = stock_universe(config, AUTO_UNIVERSE_PER_ASSET)
        candidates = screen_universe(crypto, stocks, _today_iso(), AUTO_TOP_N)
        summary["universe"] = {"crypto": len(crypto), "stock": len(stocks)}
        summary["candidates"] = [str(entry["ticker"]) for entry in candidates]
        bridge = _build_bridge(config)
        derivatives = _build_derivatives_executor(config) if config.get("exec_derivatives") is True else None
        for candidate in candidates:
            result = _process_candidate(bridge, candidate, config, build_graph, derivatives)
            results.append(result)
            summary["results"].append(_result_summary(result))
    except Exception as exc:
        # outside the candidate loop: the screen or the bridge itself failed.
        # The scheduler thread must survive to try the next interval.
        summary["status"] = "failed"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        audit_log.record("autoloop_cycle_failed", error=summary["error"])
    summary["finished_at"] = utc_now_iso()
    _set_last_cycle(summary)
    if summary["status"] == "completed":
        audit_log.record("autoloop_cycle_completed", candidates=summary["candidates"],
                         results=summary["results"])
    return results


def _process_candidate(
    bridge: Any, candidate: dict, config: dict, build_graph: Callable,
    derivatives: Any | None = None,
) -> DailyResult:
    """Analyze → plan → the engine's confirm policy for one candidate.

    Stock candidates are advisory: analysis runs, but the ccxt bridge cannot
    plan for them (bridge.py:174-186), so the signal is the deliverable.
    Crypto candidates go through ``DerivativesExecutor`` when the derivatives
    executor is supplied (the cycle arms it when ``exec_derivatives`` is a
    literal True in config), else through the spot bridge. Either way plans
    are NEVER resolved here beyond ``_handle_plan`` — the 3-gate auto-confirm
    policy alone decides execute-vs-wait, and what it does not execute is
    only audited.
    """
    ticker = str(candidate["ticker"])
    asset_type = str(candidate.get("asset_type") or "crypto")
    result = DailyResult(ticker=ticker)
    try:
        graph = build_graph(config, _ANALYSTS_CRYPTO if asset_type == "crypto" else _ANALYSTS_STOCK)
        _, signal = graph.propagate(ticker, _today_iso(), asset_type=asset_type)
        result.signal = signal
        if asset_type != "crypto":
            result.reason = (
                "advisory only — signal from the stock pipeline; the venue "
                "bridge only executes crypto, so no order plan"
            )
            return result
        if derivatives is not None:
            portfolio = derivatives._bridge.sync_portfolio()
            plan = derivatives.plan_order(
                ticker, signal, portfolio=portfolio,
                leverage=_auto_leverage(derivatives.config),
            )
            if plan.side is not None:
                plan = _attach_bracket(plan, ticker, direction=_direction(signal))
            result.plan = plan
            _handle_plan(derivatives, plan, portfolio, result)
            return result
        portfolio = bridge.sync_portfolio()
        plan = bridge.plan_order(ticker, signal, portfolio=portfolio)
        if plan.side == "buy":
            plan = _attach_bracket(plan, ticker)
        result.plan = plan
        _handle_plan(bridge, plan, portfolio, result)
    except Exception as exc:  # one candidate's failure never stops the cycle
        result.reason = f"{type(exc).__name__}: {exc}"
    return result


def _default_graph_builder(config: dict, analysts: tuple[str, ...]) -> Any:
    # Lazy like server/daily._analyze: the graph import chain pulls LangChain.
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(config=config, selected_analysts=analysts)


def _build_bridge(config: dict) -> Any:
    """The venue for the cycle's plan path; tests monkeypatch this seam like
    approvals._build_bridge (engine seam bridge.py:126-129)."""
    from tradingagents.execution.bridge import ExchangeBridge

    return ExchangeBridge(config=config)


def _build_derivatives_executor(config: dict) -> Any:
    """The futures venue for the cycle's derivatives path (lazy import — the
    executor composes the same bridge, so RiskGuard/audit/redaction keep
    working unchanged). Tests monkeypatch this seam to inject a fake."""
    from tradingagents.execution.derivatives import DerivativesExecutor

    return DerivativesExecutor(config=config)


def _auto_leverage(config: dict) -> float:
    """Leverage the cycle requests from the derivatives path: the configured
    ``risk_max_derivatives_leverage`` clamped to MAX_AUTO_LEVERAGE. A missing
    config entry means 1x — the same default as RiskLimits."""
    raw = config.get("risk_max_derivatives_leverage")
    configured = 1.0 if raw is None else float(raw)
    return min(configured, MAX_AUTO_LEVERAGE)


def _direction(signal: str) -> str:
    """Bracket direction for a 5-tier signal: Sell/Underweight open shorts on
    the derivatives path, so their bracket mirrors the long side."""
    return "short" if signal in (_SELL, _UNDERWEIGHT) else "long"


def _attach_bracket(plan: Any, ticker: str, direction: str = "long") -> Any:
    """ATR-derived protective exits on an entry plan (server/daily.py's live
    path, direction-aware for derivatives): a long stops below and targets
    above entry, a short mirrors that. A missing ATR leaves the plan
    bracket-less rather than inventing numbers — the audit shows why."""
    from tradingagents.dataflows.screening import atr_targets_signed

    stop, take = atr_targets_signed(ticker, _today_iso(), direction)
    if stop is None or take is None:
        return plan
    return plan.model_copy(update={"stop_loss": stop, "take_profit": take})


def _result_summary(result: DailyResult) -> dict:
    plan = result.plan
    return {
        "ticker": result.ticker,
        "signal": result.signal,
        "executed": result.executed,
        "order_id": result.order_id,
        "reason": result.reason,
        "stop_loss": getattr(plan, "stop_loss", None) if plan is not None else None,
        "take_profit": getattr(plan, "take_profit", None) if plan is not None else None,
    }


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --- endpoints ----------------------------------------------------------------


def _payload() -> dict:
    state = _load_state()
    return {
        "generated_at": utc_now_iso(),
        "enabled": bool(state.get("enabled", False)),
        "interval_minutes": _interval_from(state),
        "running_cycle": _cycle_lock.locked(),
        "gates": gates(),
        "last_cycle": _last_cycle,
    }


@router.get("/autoloop")
def get_autoloop():
    return _payload()


@router.post("/autoloop")
async def set_autoloop(request: Request):
    body = await json_body(request)
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise ApiError(400, "validation_error", '"enabled" must be a boolean')
    interval = body.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)
    if (
        isinstance(interval, bool)
        or not isinstance(interval, int)
        or not MIN_INTERVAL_MINUTES <= interval <= MAX_INTERVAL_MINUTES
    ):
        raise ApiError(
            400, "validation_error",
            f'"interval_minutes" must be an integer between {MIN_INTERVAL_MINUTES} and {MAX_INTERVAL_MINUTES}',
        )
    state = gates()
    if enabled and not state["all_open"]:
        raise ApiError(
            409, "gate_closed",
            "enabling the autoloop requires the auto-confirm gates open "
            "(exec_auto_confirm=True in config AND TRADINGAGENTS_EXEC_AUTO_CONFIRM=true "
            "in the environment); the engine's own policy stays fail-closed",
            {"gates": state},
        )
    _save_state({"enabled": enabled, "interval_minutes": interval, "updated_at": utc_now_iso()})
    audit_log.record("autoloop_updated", enabled=enabled, interval_minutes=interval)
    if enabled:
        ensure_started()
    _wakeup.set()  # a changed interval or enabled flag takes effect on the next wake
    return _payload()


@router.post("/autoloop/run-now", status_code=202)
async def run_autoloop_now(request: Request):
    """Run one cycle now on a worker thread. ``skipped_busy`` is the
    best-effort hint read before the spawn; the cycle itself re-checks and
    writes the ``autoloop_cycle_skipped`` trail if a run/job is active."""
    await json_body(request)  # CSRF §0: application/json required, body may be {}
    if _cycle_lock.locked():
        status = "already_running"
    else:
        busy = runs_mod.active_run_id() is not None or daily_mod.active_job_id() is not None
        status = "skipped_busy" if busy else "started"
        _spawn_cycle()
    return {"generated_at": utc_now_iso(), "status": status}


@router.post("/halt")
async def halt_now(request: Request):
    """The emergency STOP button: one halt line in the shared execution audit
    log and the RiskGuard of every process refuses the rest of today. Never
    gated — a kill switch must always work."""
    await json_body(request)  # CSRF §0: application/json required, body may be {}
    # The timestamp is what makes the halt day-scoped (risk.py:111-119): a
    # halt line without one would be ignored by _halted_today.
    append_event(get_config()["exec_log_path"], {
        "event": "halt",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": "manual halt from the control panel",
    })
    audit_log.record("autoloop_halt")
    return {"generated_at": utc_now_iso(), "halted": True}


@router.post("/halt/reset")
async def reset_halt(request: Request):
    """Lift today's halt: a halt_reset line today ends the sticky halt
    (risk.py:163-173) until a new breach or a new halt line."""
    await json_body(request)  # CSRF §0: application/json required, body may be {}
    append_event(get_config()["exec_log_path"], {
        "event": "halt_reset",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    audit_log.record("autoloop_halt_reset")
    return {"generated_at": utc_now_iso(), "halted": False}
