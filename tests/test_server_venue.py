"""API tests for the Binance Demo / production venue switch (server/venue.py)."""

import pytest
from fastapi.testclient import TestClient

from server import autoloop, control_store, venue as venue_mod
from server.main import app
from tradingagents.dataflows.config import get_config, set_config

pytestmark = pytest.mark.unit

_JSON = {"Content-Type": "application/json"}
_DEMO = "https://demo-api.binance.com"
_PROD = "https://api.binance.com"


@pytest.fixture()
def client(postgres_schema, monkeypatch):
    monkeypatch.setattr(autoloop, "cycle_running", lambda: False)
    set_config({"exec_exchange_id": "binance", "exec_base_url": _DEMO, "exec_live": False})
    for name in ("BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET", "BINANCE_API_KEY", "BINANCE_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as test_client:
        yield test_client
    set_config({"exec_base_url": _DEMO})


def _arm_production_keys(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "prod-key")
    monkeypatch.setenv("BINANCE_SECRET", "prod-secret")


def test_get_reports_current_venue_and_credential_presence(client, monkeypatch):
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "demo-key")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "demo-secret")
    body = client.get("/api/venue").json()
    assert body["supported"] is True
    assert body["venue"] == "demo"
    assert body["venues"]["demo"]["credentials"]["configured"] is True
    assert body["venues"]["production"]["credentials"] == {
        "key_env": "BINANCE_API_KEY", "secret_env": "BINANCE_SECRET", "configured": False,
    }
    assert "demo-key" not in str(body)  # presence only, never the value


def test_switch_to_production_applies_persists_and_audits(client, monkeypatch):
    _arm_production_keys(monkeypatch)
    response = client.put("/api/venue", json={"venue": "production"}, headers=_JSON)
    assert response.status_code == 200
    assert response.json()["venue"] == "production"
    assert get_config()["exec_base_url"] == _PROD
    assert control_store.load_setting("venue")["venue"] == "production"
    events = [e for e in control_store.load_server_audit() if e["action"] == "venue_switched"]
    assert events[-1]["venue"] == {"from": "demo", "to": "production"}

    # restart: the stored choice wins over the .env/default host
    set_config({"exec_base_url": _DEMO})
    venue_mod.apply_stored_venue()
    assert get_config()["exec_base_url"] == _PROD


def test_switch_without_target_credentials_is_refused(client):
    response = client.put("/api/venue", json={"venue": "production"}, headers=_JSON)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credentials_missing"
    assert get_config()["exec_base_url"] == _DEMO


def test_switch_during_a_cycle_is_refused(client, monkeypatch):
    _arm_production_keys(monkeypatch)
    monkeypatch.setattr(autoloop, "cycle_running", lambda: True)
    response = client.put("/api/venue", json={"venue": "production"}, headers=_JSON)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "venue_busy"
    assert get_config()["exec_base_url"] == _DEMO


def test_unknown_venue_is_rejected(client):
    response = client.put("/api/venue", json={"venue": "https://evil.example"}, headers=_JSON)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_switch_does_not_touch_execution_gates(client, monkeypatch):
    _arm_production_keys(monkeypatch)
    client.put("/api/venue", json={"venue": "production"}, headers=_JSON)
    assert get_config()["exec_live"] is False
    assert client.get("/api/venue").json()["effective_exec_mode"] == "dry"


def test_non_binance_exchange_is_unsupported(client):
    set_config({"exec_exchange_id": "bybit"})
    try:
        assert client.get("/api/venue").json()["supported"] is False
        response = client.put("/api/venue", json={"venue": "production"}, headers=_JSON)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "venue_unsupported"
    finally:
        set_config({"exec_exchange_id": "binance"})
