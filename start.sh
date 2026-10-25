#!/usr/bin/env bash
# TradingAgents Control Panel launcher for macOS/Linux.
# Mirrors start.bat: starts backend (uvicorn) and frontend (Next.js), waits for health, opens browser.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/.venv/bin/python"
UVICORN="$SCRIPT_DIR/.venv/bin/uvicorn"

if [[ ! -x "$PYTHON" ]]; then
    echo "[ERROR] .venv/bin/python not found"
    echo "        Install first: $SCRIPT_DIR/.venv/bin/python -m pip install -e \".[dev,web]\""
    exit 1
fi

echo "======================================================="
echo "  TradingAgents Control Panel - System launcher"
echo "======================================================="
echo

# --- frontend deps --------------------------------------------------------
if [[ ! -d "web/node_modules" ]]; then
    echo "[SETUP] web/node_modules missing - running npm install (first run may take 1-2 min)..."
    (cd web && npm install) || {
        echo "[ERROR] npm install failed - check network / Node.js."
        exit 1
    }
fi

# --- backend ---------------------------------------------------------------
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "[i] Backend already running on port 8000 - leaving existing instance."
else
    echo "[i] Starting backend FastAPI on port 8000..."
    nohup "$UVICORN" server.main:app --host 127.0.0.1 --port 8000 >"$SCRIPT_DIR/backend.log" 2>&1 &
    echo $! >"$SCRIPT_DIR/backend.pid"
fi

# --- frontend --------------------------------------------------------------
if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "[i] Frontend already running on port 3000 - leaving existing instance."
else
    echo "[i] Starting frontend Next.js on port 3000..."
    (cd web && nohup npm run dev >"$SCRIPT_DIR/frontend.log" 2>&1 &)
    echo $! >"$SCRIPT_DIR/frontend.pid"
fi

# --- wait for backend ------------------------------------------------------
echo "[i] Waiting for backend health check..."
TRIES=0
MAX_TRIES=30
while ! curl -sf -m 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; do
    TRIES=$((TRIES + 1))
    if [[ $TRIES -ge $MAX_TRIES ]]; then
        echo "[WARNING] Backend did not respond after $((MAX_TRIES * 2)) seconds - check backend.log"
        break
    fi
    sleep 2
done

if [[ $TRIES -lt $MAX_TRIES ]]; then
    echo "[i] Backend is ready."
fi

# --- open browser ------------------------------------------------------------
echo "[i] Opening browser..."
if command -v open >/dev/null 2>&1; then
    open http://localhost:3000
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:3000
else
    echo "[i] Open http://localhost:3000 manually."
fi

echo
echo "======================================================="
echo "  Started:"
echo "    - UI       : http://localhost:3000"
echo "    - Backend  : http://127.0.0.1:8000/api/health"
echo "  Logs:"
echo "    - backend  : $SCRIPT_DIR/backend.log"
echo "    - frontend : $SCRIPT_DIR/frontend.log"
echo "======================================================="
