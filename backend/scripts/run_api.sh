#!/usr/bin/env bash
# Run The Estimator API (offline stub provider by default).
#
# Usage:
#   ./scripts/run_api.sh                 # 127.0.0.1:8000 (auto-uses backend/.venv if present)
#   HOST=0.0.0.0 PORT=8080 ./scripts/run_api.sh
#
# The Python interpreter can be overridden with PYTHON=/path/to/python.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

cd "$BACKEND_DIR"
exec "$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
