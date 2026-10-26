"""Sign in with ChatGPT, so a run uses the person's ChatGPT Plus or Pro plan.

This follows OpenAI's documented flow for open-source apps ("Sign in with ChatGPT":
developers.openai.com/siwc): dynamic client registration, PKCE, and a loopback
redirect on 127.0.0.1. The sign-in, its tokens and this host's id live in one file
under ~/.tradingagents, readable only by its owner. Access tokens last an hour and
are refreshed under a lock shared by every thread and process, because each refresh
rotates the refresh token and replaying a used one ends the sign-in.
"""

import json
import os
import secrets
import threading
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from tradingagents.default_config import _TRADINGAGENTS_HOME

_CREDS_DIR = Path(_TRADINGAGENTS_HOME) / "chatgpt_cred"
_CREDS_FILE = _CREDS_DIR / "cred.json"

# OpenAI's dynamic client registration endpoint (SIWC).
_REG_ENDPOINT = "https://api.openai.com/v1/oauth/dynamic_client_registration"
_AUTH_ENDPOINT = "https://chatgpt.com/oauth/authorize"
_TOKEN_ENDPOINT = "https://api.openai.com/v1/oauth/token"
# The host this app uses for the loopback redirect.
_REDIRECT_HOST = "127.0.0.1"
# The port is chosen at runtime; 0 means "pick a free one".
_REDIRECT_PORT = 0
# Scopes required for a ChatGPT plan.
_SCOPES = "openid profile email model.identity model.read"

# ----------------------------------------------------------------------
# Credential storage
# ----------------------------------------------------------------------


def _load_creds() -> dict | None:
    """Load the stored credential, or return None if absent/corrupt."""
    try:
        with _CREDS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_creds(creds: dict) -> None:
    """Atomically write the credential file (owner-only)."""
    _CREDS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CREDS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(creds, f)
    tmp.chmod(0o600)
    os.replace(tmp, _CREDS_FILE)


# ----------------------------------------------------------------------
# PKCE helpers
# ----------------------------------------------------------------------


def _new_code_verifier() -> str:
    """Generate a PKCE code_verifier (43-128 chars, URL-safe)."""
    return secrets.token_urlsafe(64)[:128]


def _code_challenge(verifier: str) -> str:
    """Derive the S256 code_challenge from a verifier."""
    import base64
    import hashlib

    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


# ----------------------------------------------------------------------
# Loopback HTTP server for the redirect
# ----------------------------------------------------------------------


class _CallbackHandler(BaseHTTPRequestHandler):
    """Capture the authorization code from OpenAI's redirect."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        self.server.auth_code = query.get("code", [None])[0]
        self.server.auth_error = query.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>Sign-in complete.</h1>"
            b"<p>You may close this window and return to the terminal.</p>"
            b"</body></html>"
        )

    def log_message(self, format, *args):
        pass  # suppress default log


def _run_callback_server(port: int) -> tuple[str | None, str | None]:
    """Run the loopback server once and return (code, error)."""
    server = HTTPServer((_REDIRECT_HOST, port), _CallbackHandler)
    server.auth_code = None
    server.auth_error = None
    server.handle_request()
    return server.auth_code, server.auth_error


# ----------------------------------------------------------------------
# Dynamic client registration
# ----------------------------------------------------------------------


def _register_client() -> tuple[str, str]:
    """Register this app as a dynamic OAuth client with OpenAI.

    Returns (client_id, client_secret).
    """
    payload = {
        "redirect_uris": [],  # filled in after port is known
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": _SCOPES,
        "client_name": "TradingAgents",
    }
    req = Request(
        _REG_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    return data["client_id"], data["client_secret"]


# ----------------------------------------------------------------------
# Token exchange / refresh
# ----------------------------------------------------------------------


def _token_request(data: dict) -> dict:
    """POST to the token endpoint and return the JSON response."""
    req = Request(
        _TOKEN_ENDPOINT,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _exchange_code_for_tokens(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        }
    )


def _refresh_tokens(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict:
    return _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


_REFRESH_LOCK = threading.Lock()
_CREDS_CACHE: dict | None = None


def _ensure_signed_in() -> dict:
    """Return a valid credential dict, performing sign-in if needed."""
    global _CREDS_CACHE
    creds = _load_creds()
    if creds is None:
        creds = _sign_in()
    _CREDS_CACHE = creds
    return creds


def _sign_in() -> dict:
    """Run the full SIWC flow and store the credential."""
    # 1. Register client
    client_id, client_secret = _register_client()

    # 2. Pick a free loopback port
    with HTTPServer((_REDIRECT_HOST, 0), _CallbackHandler) as tmp:
        port = tmp.server_port

    # 3. Register redirect URI with the chosen port
    redirect_uri = f"http://{_REDIRECT_HOST}:{port}/callback"
    # Re-register with the real redirect URI
    client_id, client_secret = _register_client_with_redirect(port)

    # 3. Build authorization URL
    code_verifier = _new_code_verifier()
    code_challenge = _code_challenge(code_verifier)
    auth_url = (
        f"{_AUTH_ENDPOINT}?"
        f"client_id={urllib.parse.quote(client_id)}&"
        f"response_type=code&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"scope={urllib.parse.quote(_SCOPES)}&"
        f"code_challenge={code_challenge}&"
        f"code_challenge_method=S256"
    )

    # 4. Open browser / print URL
    import webbrowser

    print(f"Opening browser for ChatGPT sign-in...\n{auth_url}")
    webbrowser.open(auth_url)

    # 5. Wait for callback
    code, error = _run_callback_server(port)
    if error:
        raise RuntimeError(f"ChatGPT sign-in failed: {error}")
    if not code:
        raise RuntimeError("No authorization code received")

    # 6. Exchange code for tokens
    tokens = _exchange_code_for_tokens(
        client_id, client_secret, code, redirect_uri, code_verifier
    )

    # 7. Store credential
    creds = {
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": time.time() + tokens.get("expires_in", 3600),
    }
    _save_creds(creds)
    return creds


def _register_client_with_redirect(port: int) -> tuple[str, str]:
    """Register client with a specific redirect URI."""
    redirect_uri = f"http://{_REDIRECT_HOST}:{port}/callback"
    payload = {
        "redirect_uris": [redirect_uri],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": _SCOPES,
        "client_name": "TradingAgents",
    }
    req = Request(
        _REG_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    return data["client_id"], data["client_secret"]


def _refresh_access_token(creds: dict) -> dict:
    """Refresh the access token using the refresh token."""
    with _REFRESH_LOCK:
        # Double-check after acquiring lock
        if time.time() < creds.get("expires_at", 0) - 30:
            return creds
        tokens = _refresh_tokens(
            creds["client_id"], creds["client_secret"], creds["refresh_token"]
        )
        creds.update(
            {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "expires_at": time.time() + tokens.get("expires_in", 3600),
            }
        )
        _save_creds(creds)
        return creds


def credential() -> Callable[[], str]:
    """Return a callable that yields a fresh access token for the ChatGPT plan.

    Usage:
        cred = credential()
        # Inside a request:
        headers = {"Authorization": f"Bearer {cred()}"}

    The callable blocks briefly if a refresh is in progress.
    """

    def _token() -> str:
        creds = _ensure_signed_in()
        creds = _refresh_access_token(creds)
        return creds["access_token"]

    return _token
