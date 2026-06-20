#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh  –  Start the OCR Form Validator (backend + frontend)
#
# Usage:
#   bash start.sh            # starts both services
#   bash start.sh --backend  # backend only
#   bash start.sh --frontend # frontend only
#
# The script auto-creates a Python venv inside backend/.venv on first run
# and installs all requirements. Subsequent runs skip the install if the
# venv already exists (pass --reinstall to force a fresh pip install).
# ─────────────────────────────────────────────────────────────────────────────

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"

BACKEND_PORT=8000
FRONTEND_URL="http://localhost:5173"
BACKEND_URL="http://localhost:$BACKEND_PORT"

# ── colour helpers ─────────────────────────────────────────────────────────
GREEN="\033[0;32m"
CYAN="\033[0;36m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

log()  { echo -e "${CYAN}[start]${RESET} $*"; }
ok()   { echo -e "${GREEN}[  ok ]${RESET} $*"; }
warn() { echo -e "${YELLOW}[ warn]${RESET} $*"; }
err()  { echo -e "${RED}[error]${RESET} $*" >&2; }

# ── find a usable python3 ──────────────────────────────────────────────────
find_python() {
    for py in python3 python python3.11 python3.10 python3.9; do
        if command -v "$py" &>/dev/null; then
            local ver
            ver="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"
            local major minor
            major="${ver%%.*}"
            minor="${ver##*.}"
            if [[ "$major" -ge 3 && "$minor" -ge 9 ]]; then
                echo "$py"
                return 0
            fi
        fi
    done
    err "Python 3.9+ not found. Install it and re-run."
    exit 1
}

# ── venv setup ─────────────────────────────────────────────────────────────
setup_venv() {
    local reinstall="${1:-}"
    local py
    py="$(find_python)"

    if [[ ! -d "$VENV" ]]; then
        log "Creating virtual environment at backend/.venv …"
        "$py" -m venv "$VENV"
        ok "Virtual environment created (Python $("$py" --version 2>&1))"
        reinstall="yes"   # always install on first creation
    fi

    # Activate the venv for this script's shell session
    # shellcheck disable=SC1091
    if [[ -f "$VENV/Scripts/activate" ]]; then
        source "$VENV/Scripts/activate"   # Windows (Git Bash / MSYS2)
    elif [[ -f "$VENV/bin/activate" ]]; then
        source "$VENV/bin/activate"       # macOS / Linux
    else
        err "Cannot find venv activate script – venv may be broken. Delete backend/.venv and retry."
        exit 1
    fi

    ok "Using Python: $(python --version 2>&1)"

    if [[ "$reinstall" == "--reinstall" || "$reinstall" == "yes" ]]; then
        log "Installing requirements from backend/requirements.txt …"
        pip install --quiet --upgrade pip
        pip install --quiet -r "$BACKEND/requirements.txt"
        ok "Dependencies installed."
    else
        log "Venv already exists – skipping install. Pass --reinstall to force."
    fi
}

# ── PID tracking for clean shutdown ───────────────────────────────────────
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    log "Shutting down…"
    [[ -n "$BACKEND_PID"  ]] && kill "$BACKEND_PID"  2>/dev/null && ok "Backend stopped  (pid $BACKEND_PID)"
    [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null && ok "Frontend stopped (pid $FRONTEND_PID)"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── start backend ──────────────────────────────────────────────────────────
start_backend() {
    log "Starting backend on $BACKEND_URL …"
    cd "$BACKEND"
    uvicorn main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT" &
    BACKEND_PID=$!
    ok "Backend PID $BACKEND_PID"
    cd "$ROOT"
}

# ── start frontend ─────────────────────────────────────────────────────────
start_frontend() {
    log "Starting frontend …"
    cd "$FRONTEND"
    if [[ ! -d node_modules ]]; then
        log "node_modules not found – running npm install first …"
        npm install
        ok "npm install done."
    fi
    npm run dev &
    FRONTEND_PID=$!
    ok "Frontend PID $FRONTEND_PID"
    cd "$ROOT"
}

# ── main ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}║    OCR Form Validator – startup script   ║${RESET}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${RESET}"
echo ""

# Pull latest changes from git
if command -v git &>/dev/null; then
    log "Checking for updates from repository..."
    git pull
else
    # Also check typical Windows Git installation if running in Git Bash/MSYS
    if [[ -f "/c/Program Files/Git/cmd/git.exe" ]]; then
        log "Checking for updates from repository (using absolute Git path)..."
        "/c/Program Files/Git/cmd/git.exe" pull
    elif [[ -f "C:\Program Files\Git\cmd\git.exe" ]]; then
        log "Checking for updates from repository (using absolute Git path)..."
        "C:\Program Files\Git\cmd\git.exe" pull
    else
        warn "Git not found in PATH – skipping repository updates check."
    fi
fi
echo ""

# parse args – first arg may be a mode flag; --reinstall can appear anywhere
MODE=""
REINSTALL=""
for arg in "$@"; do
    case "$arg" in
        --backend|--frontend) MODE="$arg" ;;
        --reinstall)          REINSTALL="--reinstall" ;;
    esac
done

case "$MODE" in
    --backend)
        setup_venv "$REINSTALL"
        start_backend
        ;;
    --frontend)
        start_frontend
        ;;
    *)
        setup_venv "$REINSTALL"
        start_backend
        sleep 2      # give uvicorn a moment before the frontend proxy connects
        start_frontend
        ;;
esac

log "Press Ctrl+C to stop all services."
echo ""
echo -e "  Backend  → ${CYAN}$BACKEND_URL/docs${RESET}"
echo -e "  Frontend → ${CYAN}$FRONTEND_URL${RESET}"
echo ""

wait
