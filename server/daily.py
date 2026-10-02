"""Daily jobs: POST /api/daily + GET /api/daily/{job_id} (docs/ui-api-contract.md §5).

The worker runs the per-coin loop on the engine's own seams instead of calling
``run_daily`` (contract §5 rev 3): items are enqueued the moment a coin
finishes, ``mode: "mock"`` reuses the runs.py replay machinery instead of
building a graph, and a job clicked from the UI NEVER executes — the engine's
auto-confirm policy belongs to the unattended cron surface, while every UI
plan resolves through the approval gate (§4). One job at a time, sharing
runs.py's registry lock: ``set_config`` is process-wide (trading_graph.py:65),
so a run and a job — or two jobs — would fight over config.

``auto: true`` (rev 4) is the one-click market scan: instead of a manual
watchlist, the worker screens a universe (crypto top-volume via ccxt public
data + US large caps via the Yahoo screener), ranks candidates by a technical
score, and runs the LLM pipeline only on the top ``top_n``. The screen is the
cheap stage; its results ride on the job payload as ``screening``. Stock
candidates are advisory: analysis runs, but the ccxt bridge cannot plan for
them, so their result records the reason and no plan.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from server import (
    approvals as approvals_mod,
    audit as audit_log,
    runs as runs_mod,
    watchlist as watchlist_mod,
)
from server.contract import ApiError, json_body, utc_now_iso
from tradingagents.agents.rating import parse_rating
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.symbols import crypto_base

router = APIRouter(prefix="/api", tags=["daily"])

ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "failed"}

_PROPAGATE_ATTEMPTS = 3
# Seconds before the first propagate retry, then linear per attempt — mirrors
# the engine's unattended runner (execution/daily.py:62).
PROPAGATE_RETRY_WAIT = 20.0

# Auto-scan tuning: how many universe entries to pull per market, and how many
# screened candidates graduate into the expensive LLM pipeline.
AUTO_UNIVERSE_PER_ASSET = 12
AUTO_DEFAULT_TOP_N = 5
AUTO_MAX_TOP_N = 20

# Stub-venue fixtures for mock jobs: fixed price/cash so the whole plan path
# (sync_portfolio + plan_order) stays offline (contract §5 step 2). The balance
# is quote-only on purpose: any base-currency position would push a full Buy
# plan past the 25% per-asset cap and the demo would enqueue nothing.
MOCK_PRICE = 83078.0
MOCK_CASH = 9500.0

# Mock auto-scan must not touch ccxt/yfinance: a fixed candidate list keeps the
# demo deterministic and offline, mirroring runs.py's synthetic fallback.
MOCK_AUTO_CANDIDATES: tuple[dict, ...] = (
    {"ticker": "BTC-USD", "asset_type": "crypto", "score": 2.4,
     "last_close": MOCK_PRICE, "momentum_pct": 6.1, "trend_pct": 3.2,
     "volume_ratio": 1.8, "reasons": ["+6.1% trong 20 phiên", "giá trên SMA20 (xu hướng tăng)"]},
    {"ticker": "ETH-USD", "asset_type": "crypto", "score": 1.1,
     "last_close": 3120.5, "momentum_pct": 2.2, "trend_pct": 1.1,
     "volume_ratio": 1.2, "reasons": []},
    {"ticker": "NVDA", "asset_type": "stock", "score": 1.9,
     "last_close": 187.4, "momentum_pct": 8.4, "trend_pct": 4.5,
     "volume_ratio": 1.2, "reasons": ["+8.4% trong 20 phiên", "giá trên SMA20 (xu hướng tăng)"]},
)

logger = logging.getLogger(__name__)


@dataclass
class DailyJobState:
    job_id: str
    mode: str
    tickers: list[str]
    created_at: str
    status: str = "queued"
    finished_at: str | None = None
    results: list[dict] = field(default_factory=list)
    asset_types: dict[str, str] = field(default_factory=dict)
    screening: dict | None = None
    auto_top_n: int | None = None


_jobs: dict[str, DailyJobState] = {}


def _active_job() -> DailyJobState | None:
    """The job currently occupying the worker; callers hold the registry lock."""
    return next((job for job in _jobs.values() if job.status in ACTIVE_STATUSES), None)


def active_job_id() -> str | None:
    with runs_mod._registry_lock:
        job = _active_job()
        return job.job_id if job is not None else None


def _new_job_id() -> str:
    base = f"d_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    job_id = base
    suffix = 1
    while job_id in _jobs:
        suffix += 1
        job_id = f"{base}_{suffix}"
    return job_id


def _normalize_tickers(raw: list[str]) -> list[str]:
    """Strip, drop empties and dedupe keeping order (execution/daily.py:95-111)."""
    coins: list[str] = []
    for entry in raw:
        coin = str(entry).strip()
        if coin and coin not in coins:
            coins.append(coin)
    return coins


def _job_payload(job: DailyJobState) -> dict:
    payload = {
        "generated_at": utc_now_iso(),
        "job_id": job.job_id,
        "status": job.status,
        "mode": job.mode,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "tickers": list(job.tickers),
        "results": [dict(result) for result in job.results],
    }
    if job.auto_top_n is not None:
        payload["asset_types"] = dict(job.asset_types)
        payload["screening"] = job.screening
        payload["auto"] = True
        payload["top_n"] = job.auto_top_n
    return payload


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --- worker -----------------------------------------------------------------


class _StubVenue:
    """Fixture venue for mock jobs, injected through the bridge's factory seam
    (bridge.py:126-129): every answer is a constant, so sync_portfolio and
    plan_order never touch ccxt or the network. The numbers are demo data."""

    def fetch_ticker(self, symbol: str) -> dict:
        return {"last": MOCK_PRICE, "close": MOCK_PRICE}

    def load_markets(self) -> dict:
        # No market minimums: plan_order falls back to the sizing rules floor,
        # keeping the minimum single-sourced.
        return {}

    def fetch_balance(self) -> dict:
        return {"total": {"USDT": MOCK_CASH}, "free": {"USDT": MOCK_CASH}}


def _build_bridge(config: dict, mock: bool):
    """The venue for the job's plan path; tests monkeypatch this seam like
    approvals._build_bridge. A mock job pins the bridge dry so its plan lines
    and ``mode_at_plan`` always record "dry" — mock plans are demo data and can
    never execute (contract §5, invariant 2)."""
    from tradingagents.execution.bridge import ExchangeBridge

    if mock:
        return ExchangeBridge(config={**config, "exec_live": False}, exchange_factory=_StubVenue)
    return ExchangeBridge(config=config)


def _analyze(job: DailyJobState, coin: str, config: dict) -> tuple[str, str | None]:
    """One coin's analysis. Mock replays the runs.py machinery (no graph, no
    LLM, no vendor); live mirrors the engine's runner (execution/daily.py:
    147-164) — a fresh graph per attempt, because a failed propagate can leave
    LangGraph checkpoint state mid-pipeline. Returns (signal, mock_source)."""
    asset_type = job.asset_types.get(coin, "crypto")
    if job.mode == "mock":
        state_log = runs_mod._find_state_log(config, coin, _today_iso(), None)
        state = runs_mod._read_state_log(state_log) if state_log is not None else None
        if state is None:
            state = runs_mod._synthetic_state(coin, _today_iso())
            return parse_rating(str(state.get("final_trade_decision") or "")), "synthetic"
        return parse_rating(str(state.get("final_trade_decision") or "")), f"replay:{state_log}"

    signal: str | None = None
    for attempt in range(_PROPAGATE_ATTEMPTS):
        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            analysts = ("market", "social", "news")
            if asset_type == "stock":
                # The stock pipeline adds the fundamentals analyst, exactly like
                # runs.py _analysts_for (server/runs.py:79-86).
                analysts = ("market", "social", "news", "fundamentals")
            graph = TradingAgentsGraph(config=config, selected_analysts=analysts)
            _, signal = graph.propagate(coin, _today_iso(), asset_type=asset_type)
            return signal, None
        except Exception as exc:
            if attempt == _PROPAGATE_ATTEMPTS - 1:
                raise
            wait = PROPAGATE_RETRY_WAIT * (attempt + 1)
            logger.warning(
                "daily job %s: %s propagate failed (attempt %d, %s: %s); retrying in %.0fs",
                job.job_id, coin, attempt + 1, type(exc).__name__, exc, wait,
            )
            time.sleep(wait)
    raise RuntimeError("propagate exhausted its retries without a signal")  # pragma: no cover


def _plan_item(job: DailyJobState, plan) -> dict:
    """The enqueue payload (contract §4): everything the approval gate needs."""
    return {
        "daily_job_id": job.job_id,
        "run_id": None,
        "ticker": plan.ticker,
        "ccxt_symbol": plan.ccxt_symbol,
        "signal": plan.signal,
        "side": plan.side,
        "quantity": plan.quantity,
        "price_est": plan.estimated_price,
        "cost": plan.cost,
        "market": plan.market,
        "leverage": plan.leverage,
        "mode_at_plan": plan.mode,
        "plan_reason": plan.reason,
        "mock": job.mode == "mock",
    }


def _plan_detail(plan) -> dict:
    return {
        "side": plan.side,
        "quantity": plan.quantity,
        "price_est": plan.estimated_price,
        "cost": plan.cost,
        "ccxt_symbol": plan.ccxt_symbol,
        "market": plan.market,
        "leverage": plan.leverage,
        "mode_at_plan": plan.mode,
        "plan_reason": plan.reason,
    }


def _process_coin(job: DailyJobState, bridge, coin: str, config: dict) -> dict:
    """Analyze → plan → enqueue one coin; a coin's failure never stops the loop
    (execution/daily.py:170-173). The plan is never executed here — an
    actionable one goes to the approval queue and waits (§5 invariant 1)."""
    result: dict = {
        "ticker": coin, "signal": None, "reason": None,
        "plan": None, "approval_id": None, "error": None,
        "asset_type": job.asset_types.get(coin, "crypto"),
    }
    if job.mode == "mock":
        result["mock_source"] = "synthetic"
    try:
        signal, mock_source = _analyze(job, coin, config)
        result["signal"] = signal
        if mock_source is not None:
            result["mock_source"] = mock_source
        if result["asset_type"] != "crypto":
            # Advisory-only: the ccxt bridge cannot plan for non-crypto
            # tickers (bridge.py:174-186), so a stock candidate's signal is
            # the deliverable; the approval path stays crypto-executable.
            result["reason"] = (
                f"advisory only — signal from the {result['asset_type']} pipeline; "
                "the venue bridge only executes crypto, so no order plan"
            )
            return result
        if crypto_base(coin) is None:
            # A crypto-universe ticker outside the pipeline's closed
            # executable set (QNT-USD, MOVR-USD): the analysis is real and
            # quotable, but symbol_for cannot map it to a venue pair, so the
            # plan path is advisory here too — same contract as stocks.
            result["reason"] = (
                "advisory only — asset outside the executable crypto set "
                "(exec_symbol_overrides can enable planning); no order plan"
            )
            return result
        portfolio = bridge.sync_portfolio()
        plan = bridge.plan_order(coin, signal, portfolio=portfolio)
        if plan.side is None:
            result["reason"] = plan.reason  # Hold/REVIEW, sizing refusal or risk rejection
            return result
        item = approvals_mod.enqueue(_plan_item(job, plan))
        bridge.audit_plan(plan, action="awaiting_approval",
                          reason="UI daily job: plan awaits approval")
        result["reason"] = "awaiting approval"
        result["plan"] = _plan_detail(plan)
        result["approval_id"] = item["id"]
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
    return result


def _screen_candidates(config: dict, top_n: int) -> dict:
    """The cheap stage of an auto job: build both universes, rank, return the
    payload stored on the job. Vendor failures bubble — the job itself fails
    (a scan that found nothing because the venue is down is not an empty
    result, it is an outage)."""
    from tradingagents.dataflows.screening import (
        crypto_universe,
        screen_universe,
        stock_universe,
    )

    crypto = crypto_universe(config, AUTO_UNIVERSE_PER_ASSET)
    stocks = stock_universe(config, AUTO_UNIVERSE_PER_ASSET)
    candidates = screen_universe(crypto, stocks, _today_iso(), top_n)
    return {
        "universe_count": len(crypto) + len(stocks),
        "universe_crypto": len(crypto),
        "universe_stock": len(stocks),
        "candidates": candidates,
    }


def _execute_auto(job: DailyJobState, config: dict) -> None:
    """Screen first, then run the pipeline loop on the top candidates.

    The screening dict is attached to the job before the coin loop so the UI
    polling sees candidates as soon as the (fast) screen finishes. Vendor
    failures in the screen fail the job — a scan that found nothing because
    the venue is down is an outage, not an empty result.
    """
    job.status = "running"
    try:
        if job.mode == "mock":
            candidates = [dict(entry) for entry in MOCK_AUTO_CANDIDATES]
            job.screening = {
                "universe_count": len(MOCK_AUTO_CANDIDATES),
                "universe_crypto": 2,
                "universe_stock": 1,
                "candidates": candidates,
                "mock": True,
            }
        else:
            job.screening = _screen_candidates(config, job.auto_top_n or AUTO_DEFAULT_TOP_N)
            candidates = job.screening["candidates"]
        job.tickers = [str(entry["ticker"]) for entry in candidates]
        job.asset_types = {str(entry["ticker"]): str(entry["asset_type"]) for entry in candidates}
        if not job.tickers:
            job.status = "completed"
            return
        bridge = _build_bridge(config, job.mode == "mock")
        for coin in job.tickers:
            job.results.append(_process_coin(job, bridge, coin, config))
        job.status = "completed"
    except Exception as exc:  # outside the coin loop: the job itself failed
        job.status = "failed"
        audit_log.record("daily_job_failed", job_id=job.job_id,
                         error=f"{type(exc).__name__}: {exc}")
    finally:
        job.finished_at = utc_now_iso()
        audit_log.record("daily_job_completed", job_id=job.job_id, status=job.status,
                         mode=job.mode, tickers=list(job.tickers))


def _execute(job: DailyJobState, config: dict) -> None:
    job.status = "running"
    try:
        bridge = _build_bridge(config, job.mode == "mock")
        for coin in job.tickers:
            job.results.append(_process_coin(job, bridge, coin, config))
        job.status = "completed"
    except Exception as exc:  # outside the coin loop: the job itself failed
        job.status = "failed"
        audit_log.record("daily_job_failed", job_id=job.job_id,
                         error=f"{type(exc).__name__}: {exc}")
    finally:
        job.finished_at = utc_now_iso()
        audit_log.record("daily_job_completed", job_id=job.job_id, status=job.status,
                         mode=job.mode, tickers=list(job.tickers))


# --- endpoints ----------------------------------------------------------------


@router.post("/daily", status_code=202)
async def create_daily_job(request: Request):
    body = await json_body(request)
    mode = body.get("mode", "live")
    if mode not in ("live", "mock"):
        raise ApiError(400, "validation_error", '"mode" must be "live" or "mock"')
    auto = body.get("auto", False)
    if not isinstance(auto, bool):
        raise ApiError(400, "validation_error", '"auto" must be a boolean')
    top_n = body.get("top_n", AUTO_DEFAULT_TOP_N)
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= AUTO_MAX_TOP_N:
        raise ApiError(400, "validation_error",
                       f'"top_n" must be an integer between 1 and {AUTO_MAX_TOP_N}')
    if auto and mode == "mock" and body.get("tickers") is not None:
        raise ApiError(400, "validation_error",
                       '"tickers" cannot be combined with "auto": the screen picks the candidates')

    if auto:
        tickers: list[str] = []  # decided by the screen inside the worker
    elif (raw_tickers := body.get("tickers")) is None:
        tickers = watchlist_mod.current_symbols()  # the watchlist the UI manages
    else:
        if not isinstance(raw_tickers, list) or not all(isinstance(t, str) for t in raw_tickers):
            raise ApiError(400, "validation_error", '"tickers" must be a list of strings')
        tickers = _normalize_tickers(raw_tickers)
    if not auto and not tickers:
        raise ApiError(400, "validation_error",
                       "no tickers to run: the list is empty after normalization")

    config = get_config()  # snapshot: later settings changes do not touch this job
    with runs_mod._registry_lock:  # shared with POST /api/runs (contract §3, §5)
        active_run = runs_mod._active_run()
        if active_run is not None:
            raise ApiError(409, "conflict", "another run is already active",
                           {"run_id": active_run.run_id})
        busy = _active_job()
        if busy is not None:
            raise ApiError(409, "conflict", "another daily job is already active",
                           {"job_id": busy.job_id})
        job = DailyJobState(job_id=_new_job_id(), mode=mode, tickers=tickers,
                            created_at=utc_now_iso())
        if auto:
            job.auto_top_n = top_n
        _jobs[job.job_id] = job
        payload = _job_payload(job)  # snapshot: the worker may flip to "running" at once
        payload["detail_url"] = f"/api/daily/{job.job_id}"

    audit_log.record("daily_job_created", job_id=job.job_id, mode=mode, tickers=tickers,
                     auto=auto, top_n=top_n)
    threading.Thread(target=_execute_auto if auto else _execute,
                     args=(job, config), name=f"server-daily-{job.job_id}",
                     daemon=True).start()
    return payload


@router.get("/daily/{job_id}")
def get_daily_job(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        # Job state is in-memory: a server restart loses it (contract §11.2).
        raise ApiError(404, "not_found", f"daily job {job_id} not found")
    return _job_payload(job)
