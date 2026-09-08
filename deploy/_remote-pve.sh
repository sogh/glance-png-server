#!/usr/bin/env bash
# Runs ON THE PROXMOX HOST. Not meant to be invoked by hand -- pve-deploy.sh
# copies it across and calls it with GL_* environment variables set.
#
# Creates the container if missing, then pushes the code in and installs the
# service, all through pct. The container never needs sshd.
set -euo pipefail

: "${GL_CTID:?}" "${GL_NAME:?}" "${GL_TARBALL:?}" "${GL_ROOT:?}" "${GL_PORT:?}"
GL_IP="${GL_IP:-}"; GL_GW="${GL_GW:-}"; GL_BRIDGE="${GL_BRIDGE:-vmbr0}"
GL_STORAGE="${GL_STORAGE:-local-lvm}"; GL_TEMPLATE_STORAGE="${GL_TEMPLATE_STORAGE:-local}"
GL_DISK="${GL_DISK:-4}"; GL_CORES="${GL_CORES:-1}"; GL_MEMORY="${GL_MEMORY:-512}"
GL_TIMEZONE="${GL_TIMEZONE:-}"; GL_UNPRIVILEGED="${GL_UNPRIVILEGED:-1}"

command -v pct >/dev/null || { echo "error: pct not found -- is this a Proxmox host?" >&2; exit 1; }

is_running() { [[ "$(pct status "$GL_CTID" 2>/dev/null)" == "status: running" ]]; }

# When a container refuses to spawn, the useful information is in the lxc log
# and in `pct start --debug`, not in the one-line failure. Print both rather
# than making someone go looking.
dump_start_failure() {
  echo
  echo "=============================================================" >&2
  echo "container $GL_CTID was created but would not start." >&2
  echo "=============================================================" >&2
  echo >&2
  echo "--- pct config $GL_CTID ---" >&2
  pct config "$GL_CTID" 2>&1 | sed 's/^/    /' >&2 || true
  echo >&2
  echo "--- pct start $GL_CTID --debug (tail) ---" >&2
  pct start "$GL_CTID" --debug 2>&1 | tail -40 | sed 's/^/    /' >&2 || true
  echo >&2
  echo "--- /var/log/lxc/$GL_CTID.log (tail) ---" >&2
  tail -40 "/var/log/lxc/$GL_CTID.log" 2>/dev/null | sed 's/^/    /' >&2 \
    || echo "    (no lxc log at /var/log/lxc/$GL_CTID.log)" >&2
  echo >&2
  echo "The container still exists. Remove it before retrying:" >&2
  echo "    pct destroy $GL_CTID" >&2
  echo >&2
  echo "If it is an unprivileged/AppArmor problem, try:" >&2
  echo "    deploy/pve-deploy.sh --pve <host> --ip <...> --gw <...> --privileged" >&2
}

# Wait for a condition, but give up the moment the container stops running --
# no point burning 90 seconds polling a container that already died.
wait_for() {
  local label="$1" tries="$2"; shift 2
  echo "==> waiting for $label"
  for _ in $(seq 1 "$tries"); do
    if ! is_running; then
      echo "error: container stopped while waiting for $label" >&2
      dump_start_failure
      exit 1
    fi
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "error: timed out waiting for $label" >&2
  exit 1
}

if pct status "$GL_CTID" >/dev/null 2>&1; then
  echo "==> container $GL_CTID exists, reusing it"
  if ! is_running; then
    echo "==> starting $GL_CTID"
    if ! pct start "$GL_CTID"; then dump_start_failure; exit 1; fi
  fi
else
  [[ -n "$GL_IP" ]] || { echo "error: container missing and no ip given" >&2; exit 1; }

  echo "==> finding a Debian template"
  pveam update >/dev/null 2>&1 || true
  TEMPLATE="$(pveam available --section system 2>/dev/null | awk '{print $2}' \
              | grep -E '^debian-1[0-9]-standard' | sort -V | tail -1)"
  [[ -n "$TEMPLATE" ]] || { echo "error: no debian template in 'pveam available'" >&2; exit 1; }

  if ! pveam list "$GL_TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
    echo "==> downloading $TEMPLATE"
    pveam download "$GL_TEMPLATE_STORAGE" "$TEMPLATE"
  fi

  if [[ "$GL_IP" == "dhcp" ]]; then
    NET="name=eth0,bridge=$GL_BRIDGE,ip=dhcp"
  else
    NET="name=eth0,bridge=$GL_BRIDGE,ip=$GL_IP,gw=$GL_GW"
  fi

  # Deliberately no --features nesting=1: this runs a plain Python service,
  # never containers inside containers. Nesting only loosens the AppArmor
  # profile, which is surface we have no use for.
  # Created stopped, then started as a separate step so a spawn failure is
  # caught here with its log rather than surfacing later as a confusing
  # "container not running" from some unrelated command.
  echo "==> creating container $GL_CTID ($GL_NAME), unprivileged=$GL_UNPRIVILEGED"
  pct create "$GL_CTID" "$GL_TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$GL_NAME" \
    --cores "$GL_CORES" --memory "$GL_MEMORY" --swap 512 \
    --rootfs "$GL_STORAGE:$GL_DISK" \
    --net0 "$NET" \
    --unprivileged "$GL_UNPRIVILEGED" \
    --onboot 1

  echo "==> starting container $GL_CTID"
  if ! pct start "$GL_CTID"; then dump_start_failure; exit 1; fi

  wait_for "systemd inside the container" 90 pct exec "$GL_CTID" -- test -d /run/systemd/system
  wait_for "dns resolution"               60 pct exec "$GL_CTID" -- getent hosts deb.debian.org

  echo "==> installing base packages"
  pct exec "$GL_CTID" -- bash -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-dev curl ca-certificates >/dev/null
  '
fi

is_running || { echo "error: container $GL_CTID is not running" >&2; dump_start_failure; exit 1; }

echo "==> pushing code into the container"
pct exec "$GL_CTID" -- mkdir -p "$GL_ROOT"
pct push "$GL_CTID" "$GL_TARBALL" /tmp/glance-deploy.tar.gz
pct exec "$GL_CTID" -- tar xzf /tmp/glance-deploy.tar.gz -C "$GL_ROOT"
pct exec "$GL_CTID" -- rm -f /tmp/glance-deploy.tar.gz

echo "==> running install.sh in the container"
pct exec "$GL_CTID" -- env PORT="$GL_PORT" TIMEZONE="$GL_TIMEZONE" \
  bash "$GL_ROOT/deploy/install.sh"

CT_IP="$(pct exec "$GL_CTID" -- hostname -I 2>/dev/null | awk '{print $1}' || true)"
echo "GLANCE_CT_IP=${CT_IP}"
