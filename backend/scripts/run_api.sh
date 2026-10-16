#!/usr/bin/env bash
# Run The Estimator API locally (offline stub provider by default).
#
# Usage:
#   ./scripts/run_api.sh                 # 127.0.0.1:8000
#   HOST=0.0.0.0 PORT=8080 ./scripts/run_api.sh
#
# The venv can be overridden with PYTHON=/path/to/python.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-/root/venvs/estimator/bin/python}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

cd "$BACKEND_DIR"
exec "$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
