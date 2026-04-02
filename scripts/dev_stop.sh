#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT_DIR/.dev_pids"

if [[ ! -f "$PID_FILE" ]]; then
  echo "[INFO] No PID file found, trying to release common dev ports..."
  for port in 8000 3000; do
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill $pids >/dev/null 2>&1 || true
      sleep 1
      pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
      if [[ -n "$pids" ]]; then
        kill -9 $pids >/dev/null 2>&1 || true
      fi
      echo "[OK] Released port :$port"
    fi
  done
  exit 0
fi

while IFS='=' read -r name pid; do
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    echo "[OK] Stopped $name ($pid)"
  else
    echo "[INFO] $name already stopped"
  fi
done < "$PID_FILE"

rm -f "$PID_FILE"

for port in 8000 3000; do
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    kill $pids >/dev/null 2>&1 || true
    sleep 1
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids >/dev/null 2>&1 || true
    fi
  fi
done
