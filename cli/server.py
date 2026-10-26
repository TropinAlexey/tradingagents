"""CLI surface for the control-plane server: venue, operator-config and autoloop.

These commands talk to the running API server (default ``http://localhost:8000``);
set ``TRADINGAGENTS_SERVER_URL`` to point elsewhere. Every state-changing request
sends ``Content-Type: application/json`` to satisfy the server's CSRF guard.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests
import typer

from cli.display import console
from server.operator_config import ALLOWED_KEYS, GATE_KEYS

SERVER_URL = os.environ.get("TRADINGAGENTS_SERVER_URL", "http://localhost:8000")


venue_app = typer.Typer(help="Switch between Binance Demo and production venues")
operator_config_app = typer.Typer(help="Read and write operator config overrides")
autoloop_app = typer.Typer(help="Control the scheduled auto-trading loop")


def _base_url() -> str:
    return SERVER_URL.rstrip("/")


def _request(method: str, path: str, json_body: dict | None = None) -> dict:
    url = f"{_base_url()}{path}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method, url, json=json_body, headers=headers, timeout=30
        )
    except requests.RequestException as exc:
        console.print(f"[red]Cannot reach server at {SERVER_URL}: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not response.ok:
        try:
            payload = response.json()
            message = payload.get("error", {}).get("message") or response.text
        except (json.JSONDecodeError, ValueError):
            message = response.text or f"HTTP {response.status_code}"
        console.print(f"[red]{response.status_code}: {message}[/red]")
        raise typer.Exit(code=1)
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return {}


def _print_json(data: Any) -> None:
    console.print(json.dumps(data, indent=2, default=str))


def _parse_value(raw: str) -> Any:
    """Parse a CLI value the same way the server would coerce it."""
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


# ---------------------------------------------------------------------------
# venue
# ---------------------------------------------------------------------------


@venue_app.command("status")
def venue_status():
    """Show the current execution venue and available options."""
    data = _request("GET", "/api/venue")
    current = data.get("venue")
    if current is None and not data.get("supported", False):
        console.print("[yellow]Venue switching is not supported for the configured exchange.[/yellow]")
        return
    console.print(f"[bold]Current venue:[/bold] {current} ({data.get('base_url')})")
    console.print(f"Effective exec mode: {data.get('effective_exec_mode')}")
    for name, info in data.get("venues", {}).items():
        configured = "[green]configured[/green]" if info["credentials"]["configured"] else "[red]missing credentials[/red]"
        protected = info.get("protected_positions", 0)
        console.print(f"  {name}: {info['base_url']} ({configured}, protected={protected})")


@venue_app.command("switch")
def venue_switch(venue: str = typer.Argument(..., help="demo or production")):
    """Switch the execution venue to demo or production."""
    data = _request("PUT", "/api/venue", {"venue": venue})
    console.print(f"[green]Switched to {data.get('venue')} venue[/green] ({data.get('base_url')})")


# ---------------------------------------------------------------------------
# operator-config
# ---------------------------------------------------------------------------


@operator_config_app.command("show")
def operator_config_show():
    """Show current operator config overrides and gate states."""
    data = _request("GET", "/api/operator-config")
    _print_json(data)


_SETTINGS_ARG = typer.Argument(
    ...,
    help="Key=value pairs, e.g. exec_live=true risk_max_derivatives_leverage=3",
)


@operator_config_app.command("set")
def operator_config_set(
    settings: list[str] = _SETTINGS_ARG,
    reason: str = typer.Option(
        None,
        "--reason",
        help="Required when changing an execution gate (armed live/auto-confirm/derivatives).",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Confirm that you really want to arm an execution gate.",
    ),
):
    """Write operator config overrides. Arming a gate requires --confirm and --reason."""
    parsed: dict[str, Any] = {}
    for item in settings:
        if "=" not in item:
            console.print(f"[red]Setting must be key=value: {item}[/red]")
            raise typer.Exit(code=1)
        key, value = item.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_KEYS:
            console.print(f"[red]Unknown operator config key: {key}[/red]")
            console.print(f"Allowed: {sorted(ALLOWED_KEYS)}")
            raise typer.Exit(code=1)
        parsed[key] = _parse_value(value)

    gate_changes = {k for k in parsed if k in GATE_KEYS}
    if gate_changes:
        if not confirm:
            console.print(
                "[red]Changing execution gates requires --confirm[/red] "
                f"(affected: {sorted(gate_changes)})"
            )
            raise typer.Exit(code=1)
        if not reason or not reason.strip():
            console.print("[red]Changing execution gates requires --reason[/red]")
            raise typer.Exit(code=1)

    body: dict[str, Any] = {"settings": parsed}
    if gate_changes:
        body["confirm"] = True
        body["reason"] = reason.strip()

    data = _request("PUT", "/api/operator-config", body)
    _print_json(data)


@operator_config_app.command("delete")
def operator_config_delete(
    key: str = typer.Argument(..., help="Operator config key to reset to default"),
):
    """Reset one operator config key to its shipped default."""
    if key not in ALLOWED_KEYS:
        console.print(f"[red]Unknown operator config key: {key}[/red]")
        raise typer.Exit(code=1)
    data = _request("DELETE", f"/api/operator-config/{key}", {})
    _print_json(data)


# ---------------------------------------------------------------------------
# autoloop
# ---------------------------------------------------------------------------


@autoloop_app.command("status")
def autoloop_status():
    """Show autoloop state and the last cycle snapshot."""
    data = _request("GET", "/api/autoloop")
    _print_json(data)


@autoloop_app.command("enable")
def autoloop_enable(
    interval: int = typer.Option(
        60,
        "--interval",
        help="Interval between cycles in minutes (15-1440).",
    ),
):
    """Enable the scheduled autoloop."""
    data = _request("POST", "/api/autoloop", {"enabled": True, "interval_minutes": interval})
    _print_json(data)


@autoloop_app.command("disable")
def autoloop_disable():
    """Disable the scheduled autoloop."""
    data = _request("POST", "/api/autoloop", {"enabled": False})
    _print_json(data)


@autoloop_app.command("run-now")
def autoloop_run_now():
    """Trigger one autoloop cycle immediately."""
    data = _request("POST", "/api/autoloop/run-now", {})
    status = data.get("status", "unknown")
    console.print(f"[green]Autoloop cycle {status}[/green]")


@autoloop_app.command("cycles")
def autoloop_cycles(
    limit: int = typer.Option(20, "--limit", help="Number of recent cycles to fetch (1-100)."),
):
    """List recent autoloop cycles."""
    data = _request("GET", f"/api/autoloop/cycles?limit={limit}")
    _print_json(data)


# ---------------------------------------------------------------------------
# halt
# ---------------------------------------------------------------------------


def halt_cmd():
    """Emergency halt: append a halt event to the shared audit log."""
    data = _request("POST", "/api/halt", {})
    _print_json(data)


def register(app: typer.Typer) -> None:
    """Wire server command groups into the main CLI."""
    app.add_typer(venue_app, name="venue")
    app.add_typer(operator_config_app, name="operator-config")
    app.add_typer(autoloop_app, name="autoloop")
    app.command(name="halt")(halt_cmd)
