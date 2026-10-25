"""Execution venue switch: Binance Demo Trading vs production, from the UI.

One concern: which Binance host (and therefore which credential pair) the
engine trades on. The choice is ``exec_base_url``; credentials already follow
it (``bridge.credential_env_names``: BINANCE_DEMO_* for demo, BINANCE_* for
production), and every bridge is built per cycle/request from ``get_config()``,
so a switch applies to the next cycle and the next monitor poll without a
restart.

The switch selects the venue only. It does not touch the execution gates:
whether orders are sent at all is still exec_live + TRADINGAGENTS_EXEC_LIVE.

State: ``control_settings`` row ``venue`` ({"venue": "demo"|"production"}),
applied at startup over the ``.env`` default, so the choice survives a
restart. Refused (409) while a cycle, run or daily job is active — a switch
mid-cycle would split one decision across two venues — and when the target
venue has no credentials in the process environment.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request

from server import (
    audit as audit_log,
    autoloop,
    control_store,
    daily as daily_mod,
    job_store,
    runs as runs_mod,
    settings,
)
from server.contract import ApiError, json_body, utc_now_iso
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.execution.bridge import (
    binance_profile,
    credential_env_names,
    venue_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["venue"])

VENUES: dict[str, str] = {
    "demo": "https://demo-api.binance.com",
    "production": "https://api.binance.com",
}
_SETTINGS_KEY = "venue"


def _exchange_id(config: dict) -> str:
    return str(config.get("exec_exchange_id") or "").strip().lower()


def current_venue(config: dict | None = None) -> str | None:
    """"demo" / "production" for the configured Binance host, else None."""
    config = config if config is not None else get_config()
    if _exchange_id(config) != "binance":
        return None
    try:
        return binance_profile(config.get("exec_base_url") or VENUES["demo"])
    except ValueError:
        return None


def _credentials(venue: str) -> dict:
    key_env, secret_env = credential_env_names("binance", VENUES[venue])
    return {
        "key_env": key_env,
        "secret_env": secret_env,
        # Presence only: values never leave the process.
        "configured": bool(os.environ.get(key_env)) and bool(os.environ.get(secret_env)),
    }


def _venue_key(config: dict, url: str) -> str:
    return venue_key(_exchange_id(config), url, config.get("exec_sandbox") is True)


def _protected_positions(config: dict, venue: str) -> int:
    """Active protective-bracket tasks the monitor tracks on ``venue``."""
    key = _venue_key(config, VENUES[venue])
    try:
        tasks = job_store.active_bracket_recoveries()
    except Exception as exc:  # noqa: BLE001 - a count must never break the read
        logger.warning("venue: bracket tasks unavailable (%r)", exc)
        return 0
    return sum(1 for task in tasks if task.get("venue_key") == key)


def _busy_reason() -> str | None:
    if autoloop.cycle_running():
        return "an autoloop cycle is running"
    run_id = runs_mod.active_run_id()
    if run_id is not None:
        return f"run {run_id} is active"
    job_id = daily_mod.active_job_id()
    if job_id is not None:
        return f"daily job {job_id} is active"
    return None


def _payload() -> dict:
    config = get_config()
    venue = current_venue(config)
    return {
        "generated_at": utc_now_iso(),
        "supported": venue is not None,
        "venue": venue,
        "base_url": config.get("exec_base_url"),
        "effective_exec_mode": settings.effective_exec_mode(),
        "venues": {
            name: {
                "base_url": url,
                "credentials": _credentials(name),
                "protected_positions": _protected_positions(config, name),
            }
            for name, url in VENUES.items()
        },
    }


def apply_stored_venue() -> None:
    """Startup: re-apply the venue the operator last chose (over the .env default)."""
    stored = control_store.load_setting(_SETTINGS_KEY).get("venue")
    if stored not in VENUES:
        return
    if _exchange_id(get_config()) != "binance":
        logger.warning("venue: stored %r ignored, exec_exchange_id is not binance", stored)
        return
    set_config({"exec_base_url": VENUES[stored]})
    logger.info("venue: applied stored Binance %s venue", stored)


@router.get("/venue")
def get_venue():
    return _payload()


@router.put("/venue")
async def put_venue(request: Request):
    body = await json_body(request)
    target = body.get("venue")
    if target not in VENUES:
        raise ApiError(400, "validation_error", f"venue must be one of {sorted(VENUES)}")

    config = get_config()
    previous = current_venue(config)
    if previous is None:
        raise ApiError(409, "venue_unsupported", "the venue switch only applies to exec_exchange_id=binance")
    if target == previous:
        return _payload()

    busy = _busy_reason()
    if busy is not None:
        raise ApiError(409, "venue_busy", f"cannot switch venue while {busy}")
    credentials = _credentials(target)
    if not credentials["configured"]:
        raise ApiError(
            409, "credentials_missing",
            f"{target} venue needs {credentials['key_env']} and {credentials['secret_env']} in .env",
            {"key_env": credentials["key_env"], "secret_env": credentials["secret_env"]},
        )

    control_store.save_setting(_SETTINGS_KEY, {"venue": target, "updated_at": utc_now_iso()})
    set_config({"exec_base_url": VENUES[target]})
    audit_log.record(
        "venue_switched",
        changes={"exec_base_url": {"from": config.get("exec_base_url"), "to": VENUES[target]}},
        venue={"from": previous, "to": target},
        effective_exec_mode=_payload()["effective_exec_mode"],
    )
    payload = _payload()
    payload["applied_at"] = utc_now_iso()
    return payload
