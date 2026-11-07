#!/usr/bin/env bash
# Käivitab dashboardi (loob vajadusel virtuaalkeskkonna) ja avab brauseri.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
PORT="${PORT:-8501}"
if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT on juba kasutusel – dashboard ilmselt juba töötab: http://localhost:$PORT"
  open "http://localhost:$PORT" 2>/dev/null || true
  exit 0
fi
( sleep 3; open "http://localhost:$PORT" 2>/dev/null || true ) &
echo "Dashboard: http://localhost:$PORT  (peatamiseks Ctrl+C)"
exec .venv/bin/streamlit run app.py --server.port "$PORT" "$@"
