"""CLI commands for the control-plane server: venue, operator-config, autoloop, halt."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

import cli.main as main
import cli.server as server


@pytest.fixture
def runner():
    return CliRunner()


def _mock_response(json_data=None, status_code=200, text=""):
    resp = MagicMock()
    resp.ok = 200 <= status_code < 300
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text
    return resp


@patch.object(server.requests, "request")
def test_venue_status_renders_current_venue(mock_request, runner):
    mock_request.return_value = _mock_response({
        "venue": "demo",
        "base_url": "https://demo-api.binance.com",
        "supported": True,
        "effective_exec_mode": "dry",
        "venues": {
            "demo": {
                "base_url": "https://demo-api.binance.com",
                "credentials": {"configured": True},
                "protected_positions": 0,
            },
            "production": {
                "base_url": "https://api.binance.com",
                "credentials": {"configured": False},
                "protected_positions": 0,
            },
        },
    })

    result = runner.invoke(main.app, ["venue", "status"])
    assert result.exit_code == 0, result.output
    assert "demo" in result.output
    assert "https://demo-api.binance.com" in result.output
    mock_request.assert_called_once()
    assert mock_request.call_args[0][0] == "GET"
    assert mock_request.call_args[0][1].endswith("/api/venue")


@patch.object(server.requests, "request")
def test_venue_switch_sends_put(mock_request, runner):
    mock_request.return_value = _mock_response({
        "venue": "production",
        "base_url": "https://api.binance.com",
    })

    result = runner.invoke(main.app, ["venue", "switch", "production"])
    assert result.exit_code == 0, result.output
    assert "production" in result.output
    assert mock_request.call_args[0][0] == "PUT"
    assert mock_request.call_args.kwargs["json"] == {"venue": "production"}


@patch.object(server.requests, "request")
def test_operator_config_show_sends_get(mock_request, runner):
    mock_request.return_value = _mock_response({"current": {"exec_live": False}})

    result = runner.invoke(main.app, ["operator-config", "show"])
    assert result.exit_code == 0, result.output
    assert "exec_live" in result.output
    assert mock_request.call_args[0][0] == "GET"


@patch.object(server.requests, "request")
def test_operator_config_set_arming_gate_requires_confirm_and_reason(mock_request, runner):
    result = runner.invoke(main.app, ["operator-config", "set", "exec_live=true"])
    assert result.exit_code == 1
    assert "--confirm" in result.output
    mock_request.assert_not_called()


@patch.object(server.requests, "request")
def test_operator_config_set_sends_gate_with_confirm_and_reason(mock_request, runner):
    mock_request.return_value = _mock_response({"updated": ["exec_live"]})

    result = runner.invoke(main.app, [
        "operator-config", "set", "exec_live=true",
        "--confirm", "--reason", "enabling live for demo",
    ])
    assert result.exit_code == 0, result.output
    call_kwargs = mock_request.call_args.kwargs
    assert call_kwargs["json"]["settings"] == {"exec_live": True}
    assert call_kwargs["json"]["confirm"] is True
    assert call_kwargs["json"]["reason"] == "enabling live for demo"


@patch.object(server.requests, "request")
def test_autoloop_run_now_sends_post(mock_request, runner):
    mock_request.return_value = _mock_response({"status": "started"})

    result = runner.invoke(main.app, ["autoloop", "run-now"])
    assert result.exit_code == 0, result.output
    assert "started" in result.output
    assert mock_request.call_args[0][0] == "POST"
    assert mock_request.call_args[0][1].endswith("/api/autoloop/run-now")


@patch.object(server.requests, "request")
def test_halt_sends_post(mock_request, runner):
    mock_request.return_value = _mock_response({"event": "halt"})

    result = runner.invoke(main.app, ["halt"])
    assert result.exit_code == 0, result.output
    assert mock_request.call_args[0][0] == "POST"
    assert mock_request.call_args[0][1].endswith("/api/halt")


@patch.object(server.requests, "request")
def test_server_unreachable_prints_error(mock_request, runner):
    mock_request.side_effect = server.requests.RequestException("refused")

    result = runner.invoke(main.app, ["autoloop", "status"])
    assert result.exit_code == 1
    assert "Cannot reach server" in result.output


@patch.object(server.requests, "request")
def test_server_error_prints_message(mock_request, runner):
    mock_request.return_value = _mock_response(
        {"error": {"message": "venue busy"}}, status_code=409, text="conflict"
    )

    result = runner.invoke(main.app, ["venue", "switch", "production"])
    assert result.exit_code == 1
    assert "409" in result.output
    assert "venue busy" in result.output
