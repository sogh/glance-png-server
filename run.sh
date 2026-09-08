#!/usr/bin/env bash
# Start the server. Creates the venv and installs deps on first run.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
PY="$VENV/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "==> creating virtualenv in $VENV"
  python3 -m venv "$VENV"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt
fi

# Load .env if present, without clobbering anything already exported.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

read -r HOST PORT <<<"$("$PY" - <<'PYEOF'
from glance.config import load_settings
s = load_settings()
print(s.host, s.port)
PYEOF
)"

echo "==> serving on http://${HOST}:${PORT}"
echo "    preview  http://127.0.0.1:${PORT}/preview"
echo "    device   http://<your-public-host>/c/main.png"
exec "$PY" -m uvicorn glance.server:app \
  --host "$HOST" --port "$PORT" \
  --log-level "${LOG_LEVEL:-info}" \
  ${RELOAD:+--reload}
