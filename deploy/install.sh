#!/usr/bin/env bash
# Install the Glance PNG server as a systemd service.
# Run this INSIDE the LXC container (or on any Debian/Ubuntu box), as root:
#
#     bash deploy/install.sh
#
# Override defaults with environment variables:
#     PORT=80 SERVICE_USER=glance bash deploy/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SERVICE_USER:-glance}"
SERVICE_NAME="${SERVICE_NAME:-glance-png-server}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
TIMEZONE="${TIMEZONE:-}"

[[ $EUID -eq 0 ]] || { echo "error: run as root (sudo bash deploy/install.sh)" >&2; exit 1; }

echo "==> installing from $ROOT"
echo "    service : $SERVICE_NAME"
echo "    user    : $SERVICE_USER"
echo "    listen  : $HOST:$PORT"

echo "==> apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-dev ca-certificates >/dev/null

# The panel renders dates and "is it a holiday yet" against a wall clock, so
# the container's own timezone is worth getting right even though the app
# resolves its zone explicitly from config/settings.yaml.
if [[ -n "$TIMEZONE" ]]; then
  echo "==> timezone -> $TIMEZONE"
  ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime
  echo "$TIMEZONE" > /etc/timezone
fi

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  echo "==> creating system user $SERVICE_USER"
  useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "==> python virtualenv"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install --quiet --upgrade pip
"$ROOT/.venv/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt"

echo "==> permissions"
mkdir -p "$ROOT/data/cache" "$ROOT/logs"
chown -R root:"$SERVICE_USER" "$ROOT"
chmod -R g+rX "$ROOT"
# Only the state file and the ICS cache are written at runtime.
chown -R "$SERVICE_USER":"$SERVICE_USER" "$ROOT/data" "$ROOT/logs"
chmod -R g+rwX "$ROOT/data" "$ROOT/logs"
if [[ -f "$ROOT/.env" ]]; then
  chmod 640 "$ROOT/.env"
  chown root:"$SERVICE_USER" "$ROOT/.env"
fi

echo "==> systemd unit"
sed -e "s|__ROOT__|$ROOT|g" \
    -e "s|__USER__|$SERVICE_USER|g" \
    -e "s|__HOST__|$HOST|g" \
    -e "s|__PORT__|$PORT|g" \
    "$ROOT/deploy/glance-png-server.service" > "/etc/systemd/system/$SERVICE_NAME.service"

systemctl daemon-reload
systemctl enable --quiet "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "==> waiting for it to answer"
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 0.5
done

if [[ "${ok:-}" != "1" ]]; then
  echo
  echo "!! service did not answer on port $PORT. Recent log:" >&2
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager >&2
  exit 1
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
SUFFIX=""
if [[ "$PORT" != "80" ]]; then SUFFIX=":$PORT"; fi
echo
echo "    installed and running."
echo
echo "    Point the Glance private app at:"
echo "        http://${IP}${SUFFIX}/c/main.png"
echo
echo "    Preview in a browser on your network:"
echo "        http://${IP}${SUFFIX}/preview"
echo
echo "    logs:    journalctl -u $SERVICE_NAME -f"
echo "    restart: systemctl restart $SERVICE_NAME"
