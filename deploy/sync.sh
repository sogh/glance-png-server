#!/usr/bin/env bash
# Push this project to the container and restart the service.
# Run from the project directory ON YOUR MAC:
#
#     CT_HOST=192.168.1.50 deploy/sync.sh
#     deploy/sync.sh 192.168.1.50            # host as an argument also works
#
# This is the loop for iterating on artwork: export a PNG into assets/static/,
# run this, and the panel picks it up on its next refresh.
#
# Flags:
#     --with-data    also push data/todos.json (see the note below)
#     --no-restart   copy files without restarting the service
#     --dry-run      show what would transfer and change nothing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CT_HOST="${CT_HOST:-}"
SSH_USER="${SSH_USER:-root}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/glance-png-server}"
SERVICE_NAME="${SERVICE_NAME:-glance-png-server}"
PORT="${PORT:-8080}"          # must match the PORT used by deploy/install.sh
WITH_DATA=0; RESTART=1; DRY=()

for arg in "$@"; do
  case "$arg" in
    --with-data)  WITH_DATA=1 ;;
    --no-restart) RESTART=0 ;;
    --dry-run)    DRY=(--dry-run) ;;
    -*)           echo "unknown flag: $arg" >&2; exit 1 ;;
    *)            CT_HOST="$arg" ;;
  esac
done

[[ -n "$CT_HOST" ]] || { echo "error: set CT_HOST or pass the container address" >&2; exit 1; }

EXCLUDES=(
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.git/'
  --exclude '.pytest_cache/'
  --exclude '.DS_Store'
  --exclude 'logs/*'
  --exclude 'preview-frames/'
  # Runtime state belongs to the container, never to your laptop. Copying a
  # stale rotation position or ICS cache over the top would rewind the
  # carousel and could serve yesterday's calendar.
  --exclude 'data/state.json'
  --exclude 'data/cache/'
  # .env may hold a different calendar URL on each machine.
  --exclude '.env'
)

# todos.json is content, not code. Overwriting it silently would throw away
# anything edited on the server, so it moves only when you ask.
if [[ $WITH_DATA -eq 0 ]]; then
  EXCLUDES+=(--exclude 'data/todos.json')
fi

echo "==> syncing $ROOT -> $SSH_USER@$CT_HOST:$REMOTE_ROOT"
ssh "$SSH_USER@$CT_HOST" "mkdir -p '$REMOTE_ROOT'"
rsync -az --info=stats1,name0 "${DRY[@]}" "${EXCLUDES[@]}" \
  "$ROOT"/ "$SSH_USER@$CT_HOST:$REMOTE_ROOT"/

if [[ $WITH_DATA -eq 1 ]]; then
  echo "    data/todos.json: pushed (--with-data)"
else
  echo "    data/todos.json: left alone on the server (pass --with-data to push it)"
fi
echo "    .env:            left alone on the server"

if [[ ${#DRY[@]} -gt 0 ]]; then
  echo "==> dry run, nothing changed"
  exit 0
fi

if [[ $RESTART -eq 1 ]]; then
  echo "==> restarting $SERVICE_NAME"
  ssh "$SSH_USER@$CT_HOST" "systemctl restart '$SERVICE_NAME' 2>/dev/null || true"
  sleep 1
  if ssh "$SSH_USER@$CT_HOST" "curl -sf http://127.0.0.1:$PORT/healthz >/dev/null"; then
    echo "    healthy"
  else
    echo "    !! not answering -- check: ssh $SSH_USER@$CT_HOST journalctl -u $SERVICE_NAME -n 40" >&2
    exit 1
  fi
fi

SUFFIX=""
if [[ "$PORT" != "80" ]]; then SUFFIX=":$PORT"; fi
echo
echo "    device url:  http://${CT_HOST}${SUFFIX}/c/main.png"
echo "    preview:     http://${CT_HOST}${SUFFIX}/preview"
