"""Autoloop tests (server/autoloop.py): gates, state file, scheduler, cycle.

Unit-scoped like tests/test_server_api.py: a dedicated ASGI app carrying the
autoloop + health routers (main.py is not touched by this feature yet), no
sockets, no LLM, no vendors — the screen, the venue and the graph are fakes,
and the engine's audit log lives in tmp.
"""

import json
import socket
import time
import weakref
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import tradingagents.dataflows.screening as screening_mod
from server import (
    autoloop as autoloop_mod,
    daily as daily_mod,
    health as health_mod,
    paths as server_paths,
    runs as runs_mod,
)
from server.contract import install_error_handlers, utc_now_iso
from tradingagents.dataflows.config import set_config

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Shadow conftest's blanket socket refusal for ASGI tests (same shadow as
    tests/test_server_api.py: the event loop's Windows self-pipe is the only
    whitelisted socket; every other connect still refuses)."""
    if request.node.get_closest_marker("integration"):
        return

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_socketpair = socket.socketpair
    selfpipe_sockets: weakref.WeakSet[socket.socket] = weakref.WeakSet()

    def refuse_connect(self, address):
        if self in selfpipe_sockets:
            return original_connect(self, address)
        raise OSError(f"test tried to reach the network: {address}")

    def refuse_connect_ex(self, address):
        if self in selfpipe_sockets:
            return original_connect_ex(self, address)
        raise OSError(f"test tried to reach the network: {address}")

    def marked_socketpair(*args, **kwargs):
        # Windows socketpair() performs its own loopback handshake through
        # socket.connect, so the refusal must step aside for its duration,
        # then re-arm. Only the pair it returns is whitelisted afterwards.
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        try:
            first, second = original_socketpair(*args, **kwargs)
        finally:
            socket.socket.connect = refuse_connect
            socket.socket.connect_ex = refuse_connect_ex
        selfpipe_sockets.add(first)
        selfpipe_sockets.add(second)
        return first, second

    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_connect_ex)
    monkeypatch.setattr(socket, "socketpair", marked_socketpair)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@pytest.fixture(autouse=True)
def _server_state(tmp_path, monkeypatch):
    """Point all server state at tmp and reset the in-memory loop state."""
    monkeypatch.setattr(server_paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server_paths, "WATCHLIST_PATH", tmp_path / "watchlist.json")
    monkeypatch.setattr(server_paths, "APPROVALS_PATH", tmp_path / "approvals.jsonl")
    monkeypatch.setattr(server_paths, "SERVER_AUDIT_PATH", tmp_path / "server-audit.jsonl")
    monkeypatch.setattr(server_paths, "AUTOLOOP_PATH", tmp_path / "autoloop.json")
    monkeypatch.setattr(autoloop_mod, "_last_cycle", None)
    monkeypatch.setattr(autoloop_mod, "_cycle_thread", None)
    autoloop_mod._wakeup.clear()
    # A run/job planted anywhere must never leak into a cycle's busy check.
    monkeypatch.setattr(runs_mod, "_runs", {})
    monkeypatch.setattr(daily_mod, "_jobs", {})
    yield


def _test_app() -> FastAPI:
    test_app = FastAPI()
    install_error_handlers(test_app)
    test_app.include_router(autoloop_mod.router)
    test_app.include_router(health_mod.router)
    return test_app


@pytest.fixture()
def client(_server_state):
    with TestClient(_test_app()) as test_client:
        yield test_client


# --- GET /api/autoloop --------------------------------------------------------


def test_get_autoloop_defaults(client):
    body = client.get("/api/autoloop").json()
    assert body["generated_at"].endswith("Z")
    assert body["enabled"] is False
    assert body["interval_minutes"] == 1440
    assert body["running_cycle"] is False
    # conftest blanks every TRADINGAGENTS_* env var and the config defaults
    # keep every gate closed: the fail-closed default is the loop can't arm.
    assert body["gates"] == {
        "auto_confirm_config": False, "auto_confirm_env": False,
        "exec_live_config": False, "exec_live_env": False, "all_open": False,
    }
    assert body["last_cycle"] is None


# --- POST /api/autoloop: the enable gate + state file --------------------------


def test_enable_gate_closed_is_409_and_armes_nothing(client, tmp_path, monkeypatch):
    started: list[bool] = []
    monkeypatch.setattr(autoloop_mod, "ensure_started", lambda: started.append(True))
    monkeypatch.setattr(autoloop_mod, "_spawn_cycle", lambda *args, **kwargs: "started")

    response = client.post("/api/autoloop", json={"enabled": True})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "gate_closed"
    assert error["details"]["gates"]["all_open"] is False
    assert error["details"]["gates"]["auto_confirm_config"] is False

    assert not (tmp_path / "autoloop.json").exists()  # a refused enable persists nothing
    assert client.get("/api/autoloop").json()["enabled"] is False
    assert started == []  # the scheduler was never armed by a refused enable


def test_enable_with_gates_open_persists_state_and_arms_scheduler(client, tmp_path, monkeypatch):
    started: list[bool] = []
    monkeypatch.setattr(autoloop_mod, "ensure_started", lambda: started.append(True))
    monkeypatch.setattr(autoloop_mod, "_spawn_cycle", lambda *args, **kwargs: "started")

    # exec_live stays closed on purpose: enabling needs only the two
    # auto-confirm halves, exactly like _handle_plan's first two checks.
    set_config({"exec_auto_confirm": True})
    monkeypatch.setenv("TRADINGAGENTS_EXEC_AUTO_CONFIRM", "true")
    response = client.post("/api/autoloop", json={"enabled": True, "interval_minutes": 30})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["interval_minutes"] == 30
    assert body["gates"]["all_open"] is True
    assert body["gates"]["exec_live_config"] is False  # reported, never required to enable

    state = json.loads((tmp_path / "autoloop.json").read_text(encoding="utf-8"))
    assert state == {"enabled": True, "interval_minutes": 30, "updated_at": state["updated_at"]}
    assert state["updated_at"]
    assert client.get("/api/autoloop").json()["enabled"] is True
    assert started == [True]


def test_disable_is_never_gated_and_omitted_interval_defaults(client, tmp_path):
    # gates closed: turning the loop OFF must still work (the safe direction)
    response = client.post("/api/autoloop", json={"enabled": False})
    assert response.status_code == 200
    state = json.loads((tmp_path / "autoloop.json").read_text(encoding="utf-8"))
    assert state["enabled"] is False
    assert state["interval_minutes"] == 1440  # default when omitted


def test_autoloop_validates_body(client, tmp_path):
    for bad_body in (
        {"enabled": "yes"},
        {"enabled": 1},
        {"enabled": True, "interval_minutes": 10},      # below the floor
        {"enabled": True, "interval_minutes": 1441},    # above the ceiling
        {"enabled": True, "interval_minutes": True},    # bool is not an int here
        {"enabled": True, "interval_minutes": "30"},
    ):
        response = client.post("/api/autoloop", json=bad_body)
        assert response.status_code == 400, bad_body
        assert response.json()["error"]["code"] == "validation_error"
    assert not (tmp_path / "autoloop.json").exists()


# --- scheduler -----------------------------------------------------------------


def test_ensure_started_reuses_a_live_scheduler(monkeypatch):
    class _Alive:
        def is_alive(self) -> bool:
            return True

    sentinel = _Alive()
    monkeypatch.setattr(autoloop_mod, "_scheduler_thread", sentinel)
    autoloop_mod.ensure_started()
    autoloop_mod.ensure_started()
    assert autoloop_mod._scheduler_thread is sentinel  # idempotent: never a second thread


def test_scheduler_loop_re_reads_state_and_spawns_a_cycle(monkeypatch, tmp_path):
    autoloop_mod._save_state({"enabled": True, "interval_minutes": 15, "updated_at": utc_now_iso()})
    calls: list[int] = []
    monkeypatch.setattr(autoloop_mod, "_spawn_cycle", lambda *args, **kwargs: calls.append(1) or "started")

    autoloop_mod._wakeup.set()  # wake the loop at once instead of waiting 15 minutes
    autoloop_mod.ensure_started()
    deadline = time.monotonic() + 5.0
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls, "the scheduler did not wake, re-read the state file, and spawn a cycle"


# --- POST /api/autoloop/run-now -------------------------------------------------


def test_run_now_spawns_a_cycle_and_reports_already_running(client, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(autoloop_mod, "_spawn_cycle", lambda *args, **kwargs: calls.append(1) or "started")

    response = client.post("/api/autoloop/run-now", json={})
    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert calls == [1]

    with autoloop_mod._cycle_lock:  # a cycle is "in flight"
        busy = client.post("/api/autoloop/run-now", json={})
        assert busy.status_code == 202
        assert busy.json()["status"] == "already_running"
    assert calls == [1]  # the busy probe spawned nothing


def test_run_now_skipped_busy_records_the_skip_trail(client, tmp_path):
    active = runs_mod.RunState(
        run_id="r_active", ticker="BTC-USD", trade_date=_today(),
        asset_type="crypto", mode="mock", checkpoint=None, created_at=_today(),
    )
    active.status = "running"
    runs_mod._runs[active.run_id] = active

    response = client.post("/api/autoloop/run-now", json={})
    assert response.status_code == 202
    assert response.json()["status"] == "skipped_busy"

    worker = autoloop_mod._cycle_thread  # the spawn still happens; the cycle decides
    assert worker is not None
    worker.join(timeout=5.0)
    assert not worker.is_alive()

    trail = (tmp_path / "server-audit.jsonl").read_text(encoding="utf-8")
    assert "autoloop_cycle_skipped" in trail
    assert "run r_active" in trail
    assert autoloop_mod._last_cycle["status"] == "skipped_busy"


# --- kill switch: POST /api/halt + /api/halt/reset -------------------------------


def test_halt_writes_kill_switch_line_and_health_reflects_it(client, tmp_path):
    audit_file = tmp_path / "engine-audit.jsonl"
    set_config({"exec_log_path": str(audit_file)})

    response = client.post("/api/halt", json={})
    assert response.status_code == 200
    assert response.json()["halted"] is True

    events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    (halt,) = [event for event in events if event.get("event") == "halt"]
    # the timestamp is what makes the halt day-scoped (risk.py:111-119): a
    # halt line without one would be invisible to _halted_today.
    assert halt["timestamp"].startswith(_today())

    body = client.get("/api/health").json()
    assert body["halted_today"] is True


def test_halt_reset_clears_today_halt(client, tmp_path):
    audit_file = tmp_path / "engine-audit.jsonl"
    set_config({"exec_log_path": str(audit_file)})
    client.post("/api/halt", json={})

    reset = client.post("/api/halt/reset", json={})
    assert reset.status_code == 200
    assert reset.json()["halted"] is False

    events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [event.get("event") for event in events] == ["halt", "halt_reset"]
    assert client.get("/api/health").json()["halted_today"] is False


# --- the cycle: screen → pipeline → the engine's 3-gate confirm policy ----------

_STOP, _TAKE = 80246.0, 86562.0
_STUB_PRICE = 83078.0
_STUB_CASH = 9500.0


class _StubVenue:
    """Fixture venue mirroring server/daily._StubVenue: constant answers, so
    sync_portfolio and plan_order never touch ccxt or the network."""

    def fetch_ticker(self, symbol: str) -> dict:
        return {"last": _STUB_PRICE, "close": _STUB_PRICE}

    def load_markets(self) -> dict:
        return {}  # no market minimums: plan_order falls back to the rules floor

    def fetch_balance(self) -> dict:
        return {"total": {"USDT": _STUB_CASH}, "free": {"USDT": _STUB_CASH}}


class _FakeGraph:
    """propagate() returns a fixed signal and records the calls it saw."""

    def __init__(self, signal: str):
        self._signal = signal
        self.calls: list[tuple[str, str, str]] = []

    def propagate(self, ticker: str, trade_date: str, asset_type: str | None = None):
        self.calls.append((ticker, trade_date, str(asset_type)))
        return {}, self._signal


def test_run_cycle_auto_confirms_dry_buy_with_bracket(tmp_path, monkeypatch):
    """Auto-confirm dry: the third gate fully open (config literal + env flag,
    exec_live closed) — the cycle's Buy plan executes as a dry fill with the
    ATR bracket attached, exactly what _handle_plan alone decides."""
    engine_audit = tmp_path / "engine-audit.jsonl"
    set_config({"exec_auto_confirm": True, "exec_live": False, "exec_log_path": str(engine_audit)})
    monkeypatch.setenv("TRADINGAGENTS_EXEC_AUTO_CONFIRM", "true")  # the env half

    monkeypatch.setattr(screening_mod, "crypto_universe", lambda config, top_n: ["BTC-USD"])
    monkeypatch.setattr(screening_mod, "stock_universe", lambda config, top_n: ["NVDA"])
    monkeypatch.setattr(screening_mod, "screen_universe", lambda crypto, stocks, date, top_n: [
        {"ticker": "BTC-USD", "asset_type": "crypto"},
        {"ticker": "NVDA", "asset_type": "stock"},
    ])
    monkeypatch.setattr(screening_mod, "atr_targets",
                        lambda ticker, date, asset_type="crypto": (_STOP, _TAKE))

    def build(config):
        from tradingagents.execution.bridge import ExchangeBridge

        return ExchangeBridge(config=config, exchange_factory=_StubVenue)

    monkeypatch.setattr(autoloop_mod, "_build_bridge", build)

    built: list[tuple[tuple[str, ...], _FakeGraph]] = []

    def graph_builder(config, analysts):
        graph = _FakeGraph("Buy")
        built.append((tuple(analysts), graph))
        return graph

    results = autoloop_mod._run_cycle(graph_builder)

    assert [result.ticker for result in results] == ["BTC-USD", "NVDA"]
    btc, nvda = results
    assert btc.signal == "Buy"
    assert btc.executed is True  # the engine policy executed the dry fill itself
    assert btc.plan.stop_loss == _STOP and btc.plan.take_profit == _TAKE
    assert nvda.signal == "Buy"
    assert nvda.executed is False
    assert nvda.plan is None and "advisory only" in nvda.reason  # stock candidates never plan
    # analyst sets per asset type, exactly like server/daily._analyze
    assert built[0][0] == ("market", "social", "news")
    assert built[1][0] == ("market", "social", "news", "fundamentals")

    events = [json.loads(line) for line in engine_audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    plan_buys = [event for event in events if event.get("phase") == "plan" and event.get("action") == "buy"]
    (dry_buy,) = [event for event in events if event.get("phase") == "execute" and event.get("action") == "buy"]
    assert plan_buys  # the plan line was audited before the policy decided
    assert dry_buy["mode"] == "dry" and dry_buy["confirmed"] is True
    assert dry_buy["stop_loss"] == _STOP and dry_buy["take_profit"] == _TAKE
    assert all(event.get("mode") != "live" for event in events)  # never goes live on its own

    trail = (tmp_path / "server-audit.jsonl").read_text(encoding="utf-8")
    assert "autoloop_cycle_started" in trail
    assert "autoloop_cycle_completed" in trail

    last = autoloop_mod._last_cycle
    assert last["status"] == "completed"
    assert last["candidates"] == ["BTC-USD", "NVDA"]
    assert last["results"][0]["executed"] is True
    assert last["results"][1]["executed"] is False


def test_run_cycle_skips_each_failing_candidate_but_completes(tmp_path, monkeypatch):
    """One candidate's failure never stops the cycle (execution/daily.py:170-173)."""
    engine_audit = tmp_path / "engine-audit.jsonl"
    set_config({"exec_auto_confirm": True, "exec_live": False, "exec_log_path": str(engine_audit)})
    monkeypatch.setenv("TRADINGAGENTS_EXEC_AUTO_CONFIRM", "true")

    monkeypatch.setattr(screening_mod, "crypto_universe", lambda config, top_n: ["BTC-USD"])
    monkeypatch.setattr(screening_mod, "stock_universe", lambda config, top_n: [])
    monkeypatch.setattr(screening_mod, "screen_universe",
                        lambda crypto, stocks, date, top_n: [{"ticker": "BTC-USD", "asset_type": "crypto"}])

    def build(config):
        from tradingagents.execution.bridge import ExchangeBridge

        return ExchangeBridge(config=config, exchange_factory=_StubVenue)

    monkeypatch.setattr(autoloop_mod, "_build_bridge", build)

    class _BrokenGraph:
        def propagate(self, *args, **kwargs):
            raise RuntimeError("LLM relay down")

    results = autoloop_mod._run_cycle(lambda config, analysts: _BrokenGraph())

    (btc,) = results
    assert btc.executed is False
    assert btc.reason == "RuntimeError: LLM relay down"
    assert autoloop_mod._last_cycle["status"] == "completed"  # the cycle itself completed
    (completed,) = [json.loads(line) for line in
                    (tmp_path / "server-audit.jsonl").read_text(encoding="utf-8").splitlines()
                    if "autoloop_cycle_completed" in line]
    assert completed["results"][0]["reason"] == "RuntimeError: LLM relay down"
