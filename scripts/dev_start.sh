#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
PID_FILE="$ROOT_DIR/.dev_pids"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python venv not found: $PYTHON_BIN"
  echo "Please create it first, e.g.: python3 -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt"
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  echo "[INFO] Existing PID file found. Stopping previous dev services..."
  while IFS='=' read -r name pid; do
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

stop_port_if_busy() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "[INFO] Releasing port :$port ($pids)"
    kill $pids >/dev/null 2>&1 || true
    sleep 1
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids >/dev/null 2>&1 || true
    fi
  fi
}

stop_port_if_busy 8000
stop_port_if_busy 3000

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "[INFO] Installing frontend dependencies..."
  npm --prefix "$FRONTEND_DIR" install
fi

echo "[INFO] Starting backend on :8000 ..."
nohup "$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir "$BACKEND_DIR" > "$ROOT_DIR/.dev_backend.log" 2>&1 &
BACKEND_PID=$!

echo "[INFO] Starting frontend on :3000 ..."
nohup npm --prefix "$FRONTEND_DIR" run dev > "$ROOT_DIR/.dev_frontend.log" 2>&1 &
FRONTEND_PID=$!

cat > "$PID_FILE" <<EOF
backend=$BACKEND_PID
frontend=$FRONTEND_PID
EOF

sleep 2

wait_http_ok() {
  local url="$1"
  local name="$2"
  local attempts=20
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -s --max-time 3 "$url" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "[ERROR] $name failed to start. Check logs."
  return 1
}

wait_http_ok "http://localhost:8000/" "Backend" || { echo "[ERROR] $ROOT_DIR/.dev_backend.log"; exit 1; }
wait_http_ok "http://localhost:3000/" "Frontend" || { echo "[ERROR] $ROOT_DIR/.dev_frontend.log"; exit 1; }

echo "[OK] Dev services started"
echo "- Frontend: http://localhost:3000/home/forecast/dashboard"
echo "- Backend : http://localhost:8000"
echo "- Logs    : $ROOT_DIR/.dev_frontend.log , $ROOT_DIR/.dev_backend.log"
echo "- Stop    : ./scripts/dev_stop.sh"
