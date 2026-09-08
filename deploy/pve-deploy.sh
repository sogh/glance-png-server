#!/usr/bin/env bash
# Deploy (or redeploy) the Glance PNG server to a Proxmox LXC container.
# Run this FROM YOUR MAC, in the project directory. One SSH hop to the
# Proxmox host; everything inside the container happens over `pct`, so the
# container never needs sshd, keys, or to be reachable from your laptop.
#
#   first time:   deploy/pve-deploy.sh --pve root@proxmox --ip 192.168.1.50/24 --gw 192.168.1.1
#   every time:   deploy/pve-deploy.sh --pve root@proxmox
#
# It is idempotent: the same command creates the container the first time and
# updates code and artwork every time after. This is also the art loop --
# export a PNG into assets/static/, run it again.
#
# Options (all have env-var equivalents in CAPS):
#   --pve USER@HOST   Proxmox host to ssh to            (required)
#   --ctid N          container id      (default: found by name, else next free)
#   --name NAME       container hostname                (default: glance)
#   --ip A.B.C.D/NN   static address, or 'dhcp'   (required only when creating)
#   --gw A.B.C.D      gateway                     (required with a static ip)
#   --bridge NAME     network bridge                    (default: vmbr0)
#   --storage NAME    rootfs storage                    (default: local-lvm)
#   --disk N          rootfs GB                         (default: 4)
#   --cores N         cpu cores                         (default: 1)
#   --memory N        RAM in MB                         (default: 512)
#   --port N          port to serve on                  (default: 8080)
#   --timezone TZ     container timezone       (default: from settings.yaml)
#   --with-data       also push data/todos.json
#   --privileged      create a privileged container         (see note below)
#   --features LIST   pct features            (default: nesting=1, needed by
#                     systemd 257 in Debian 13 and by our unit's sandboxing)
#   --dry-run         build the tarball, show contents, change nothing
#
# --privileged is a fallback, not a default. Unprivileged containers are the
# safer choice and what you should use if they work. But on some hosts --
# notably the ARM Proxmox builds -- unprivileged LXCs fail to spawn with
# AppArmor or idmap errors. If the container will not start, this is the
# quickest way to find out whether that is why.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PVE="${PVE:-}"; CTID="${CTID:-}"; CT_NAME="${CT_NAME:-glance}"
IP="${IP:-}"; GW="${GW:-}"; BRIDGE="${BRIDGE:-vmbr0}"
STORAGE="${STORAGE:-local-lvm}"; TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
DISK="${DISK:-4}"; CORES="${CORES:-1}"; MEMORY="${MEMORY:-512}"
PORT="${PORT:-8080}"; TIMEZONE="${TIMEZONE:-}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/glance-png-server}"
UNPRIVILEGED="${UNPRIVILEGED:-1}"
FEATURES="${FEATURES:-nesting=1}"
WITH_DATA=0; DRY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pve)       PVE="$2"; shift 2 ;;
    --ctid)      CTID="$2"; shift 2 ;;
    --name)      CT_NAME="$2"; shift 2 ;;
    --ip)        IP="$2"; shift 2 ;;
    --gw)        GW="$2"; shift 2 ;;
    --bridge)    BRIDGE="$2"; shift 2 ;;
    --storage)   STORAGE="$2"; shift 2 ;;
    --disk)      DISK="$2"; shift 2 ;;
    --cores)     CORES="$2"; shift 2 ;;
    --memory)    MEMORY="$2"; shift 2 ;;
    --port)      PORT="$2"; shift 2 ;;
    --timezone)  TIMEZONE="$2"; shift 2 ;;
    --with-data) WITH_DATA=1; shift ;;
    --privileged) UNPRIVILEGED=0; shift ;;
    --features)  FEATURES="$2"; shift 2 ;;
    --dry-run)   DRY=1; shift ;;
    -h|--help)   sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$PVE" ]] || { echo "error: --pve USER@HOST is required (e.g. --pve root@proxmox)" >&2; exit 1; }

if [[ -n "$IP" && "$IP" != "dhcp" ]]; then
  [[ "$IP" == */* ]] || { echo "error: --ip needs a CIDR suffix, e.g. 192.168.1.50/24" >&2; exit 1; }
  [[ -n "$GW" ]] || { echo "error: --gw is required with a static --ip" >&2; exit 1; }
fi

# Default the container's clock to whatever the app is already configured for,
# so log timestamps line up with the dates the panel renders.
if [[ -z "$TIMEZONE" && -f "$ROOT/config/settings.yaml" ]]; then
  TIMEZONE="$(awk '/^timezone:/ {print $2; exit}' "$ROOT/config/settings.yaml" | tr -d '"'"'"'')"
fi

# --- build the payload ------------------------------------------------------
# Runtime state belongs to the container. Shipping a stale rotation position or
# ICS cache back over the top would rewind the carousel and could serve
# yesterday's calendar, so those never travel.
EXCLUDES=(
  --exclude './.venv' --exclude './.git' --exclude './.pytest_cache'
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store'
  --exclude './logs/*' --exclude './preview-frames'
  --exclude './data/state.json' --exclude './data/cache'
  --exclude './.env'
)
if [[ $WITH_DATA -eq 0 ]]; then
  EXCLUDES+=(--exclude './data/todos.json')
fi

TARBALL="$(mktemp -t glance-deploy).tar.gz"
REMOTE_SCRIPT_TMP="/tmp/glance-remote-pve.$$.sh"
cleanup() { rm -f "$TARBALL"; }
trap cleanup EXIT

echo "==> packaging $ROOT"
# COPYFILE_DISABLE stops macOS tar from adding ._ AppleDouble files.
COPYFILE_DISABLE=1 tar czf "$TARBALL" "${EXCLUDES[@]}" -C "$ROOT" .
echo "    $(du -h "$TARBALL" | awk '{print $1}') payload"

if [[ $DRY -eq 1 ]]; then
  echo "==> dry run; tarball contents:"
  tar tzf "$TARBALL" | sed 's|^\./||' | grep -v '/$' | sort | sed 's/^/    /'
  echo "==> nothing sent"
  exit 0
fi

# --- resolve the container id ----------------------------------------------
if [[ -z "$CTID" ]]; then
  echo "==> looking for an existing container named '$CT_NAME' on $PVE"
  CTID="$(ssh "$PVE" "pct list 2>/dev/null | awk 'NR>1 && \$NF==\"$CT_NAME\" {print \$1; exit}'" || true)"
  if [[ -n "$CTID" ]]; then
    echo "    found ctid $CTID"
  else
    CTID="$(ssh "$PVE" "pvesh get /cluster/nextid")"
    echo "    none found; will create ctid $CTID"
    if [[ -z "$IP" ]]; then
      cat >&2 <<'MSG'

error: creating a new container needs --ip.

  The Glance device remembers the URL you configure. If this container gets a
  new DHCP address later, the panel keeps redrawing its last cached frame and
  looks perfectly healthy while fetching nothing. Give it a fixed address
  outside your DHCP pool:

      deploy/pve-deploy.sh --pve root@proxmox --ip 192.168.1.50/24 --gw 192.168.1.1

  Or pin it by MAC reservation on your router and pass --ip dhcp.
MSG
      exit 1
    fi
  fi
fi

# --- ship it ----------------------------------------------------------------
echo "==> copying to $PVE"
scp -q "$TARBALL" "$PVE:/tmp/glance-deploy.$$.tar.gz"
scp -q "$ROOT/deploy/_remote-pve.sh" "$PVE:$REMOTE_SCRIPT_TMP"

# Passed as environment variables rather than positionally -- fifteen ordered
# arguments is a silent-corruption bug waiting to happen.
REMOTE_ENV=(
  "GL_CTID='$CTID'" "GL_NAME='$CT_NAME'" "GL_IP='$IP'" "GL_GW='$GW'"
  "GL_BRIDGE='$BRIDGE'" "GL_STORAGE='$STORAGE'" "GL_TEMPLATE_STORAGE='$TEMPLATE_STORAGE'"
  "GL_DISK='$DISK'" "GL_CORES='$CORES'" "GL_MEMORY='$MEMORY'"
  "GL_TARBALL='/tmp/glance-deploy.$$.tar.gz'" "GL_ROOT='$REMOTE_ROOT'"
  "GL_PORT='$PORT'" "GL_TIMEZONE='$TIMEZONE'" "GL_UNPRIVILEGED='$UNPRIVILEGED'"
  "GL_FEATURES='$FEATURES'"
)

set +e
OUTPUT="$(ssh "$PVE" "${REMOTE_ENV[*]} bash '$REMOTE_SCRIPT_TMP'; \
  rc=\$?; rm -f '$REMOTE_SCRIPT_TMP' '/tmp/glance-deploy.$$.tar.gz'; exit \$rc" 2>&1)"
RC=$?
set -e
echo "$OUTPUT" | grep -v '^GLANCE_CT_IP=' || true
[[ $RC -eq 0 ]] || { echo "==> deploy failed (exit $RC)" >&2; exit $RC; }

CT_IP="$(echo "$OUTPUT" | sed -n 's/^GLANCE_CT_IP=//p' | tail -1)"
[[ -n "$CT_IP" ]] || CT_IP="${IP%%/*}"
SUFFIX=""
if [[ "$PORT" != "80" ]]; then SUFFIX=":$PORT"; fi

cat <<MSG

    deployed to container $CTID at ${CT_IP:-<unknown>}

    Point the Glance private app at   http://${CT_IP}${SUFFIX}/c/main.png
    Preview from any browser at       http://${CT_IP}${SUFFIX}/preview

    logs:     ssh $PVE "pct exec $CTID -- journalctl -u glance-png-server -f"
    status:   curl -s http://${CT_IP}${SUFFIX}/api/status
    redeploy: deploy/pve-deploy.sh --pve $PVE
MSG
