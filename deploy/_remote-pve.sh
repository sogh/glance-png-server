#!/usr/bin/env bash
# Runs ON THE PROXMOX HOST. Not meant to be invoked by hand -- pve-deploy.sh
# copies it across and calls it. Creates the container if it is missing, then
# pushes the code in and installs the service, all through pct.
set -euo pipefail

CTID="$1"; CT_NAME="$2"; IP="$3"; GW="$4"; BRIDGE="$5"; STORAGE="$6"
DISK="$7"; CORES="$8"; MEMORY="$9"; TARBALL="${10}"; REMOTE_ROOT="${11}"
PORT="${12}"; TIMEZONE="${13}"; TEMPLATE_STORAGE="${14}"

command -v pct >/dev/null || { echo "error: pct not found -- is this a Proxmox host?" >&2; exit 1; }

container_exists() { pct status "$CTID" >/dev/null 2>&1; }

if container_exists; then
  echo "==> container $CTID exists, reusing it"
  if [[ "$(pct status "$CTID")" != "status: running" ]]; then
    echo "==> starting $CTID"
    pct start "$CTID"
  fi
else
  if [[ -z "$IP" ]]; then
    echo "error: container $CTID does not exist and no --ip was given." >&2
    echo "       Pass --ip to create it, e.g. --ip 192.168.1.50/24 --gw 192.168.1.1" >&2
    exit 1
  fi

  echo "==> finding a Debian template"
  pveam update >/dev/null 2>&1 || true
  TEMPLATE="$(pveam available --section system 2>/dev/null | awk '{print $2}' \
              | grep -E '^debian-1[0-9]-standard' | sort -V | tail -1)"
  [[ -n "$TEMPLATE" ]] || { echo "error: no debian template in 'pveam available'" >&2; exit 1; }

  if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
    echo "==> downloading $TEMPLATE"
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
  fi

  if [[ "$IP" == "dhcp" ]]; then
    NET="name=eth0,bridge=$BRIDGE,ip=dhcp"
  else
    NET="name=eth0,bridge=$BRIDGE,ip=$IP,gw=$GW"
  fi

  echo "==> creating container $CTID ($CT_NAME)"
  pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$CT_NAME" \
    --cores "$CORES" --memory "$MEMORY" --swap 512 \
    --rootfs "$STORAGE:$DISK" \
    --net0 "$NET" \
    --unprivileged 1 --features nesting=1 \
    --onboot 1 --start 1

  echo "==> waiting for systemd inside the container"
  for _ in $(seq 1 90); do
    pct exec "$CTID" -- test -d /run/systemd/system 2>/dev/null && break
    sleep 1
  done

  echo "==> waiting for network"
  for _ in $(seq 1 60); do
    pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
    sleep 1
  done

  # No openssh-server: everything below goes through pct, so the container
  # never needs to accept an inbound SSH connection.
  echo "==> installing base packages"
  pct exec "$CTID" -- bash -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-dev curl ca-certificates >/dev/null
  '
fi

echo "==> pushing code into the container"
pct exec "$CTID" -- mkdir -p "$REMOTE_ROOT"
pct push "$CTID" "$TARBALL" /tmp/glance-deploy.tar.gz
pct exec "$CTID" -- tar xzf /tmp/glance-deploy.tar.gz -C "$REMOTE_ROOT"
pct exec "$CTID" -- rm -f /tmp/glance-deploy.tar.gz

echo "==> running install.sh in the container"
pct exec "$CTID" -- env PORT="$PORT" TIMEZONE="$TIMEZONE" \
  bash "$REMOTE_ROOT/deploy/install.sh"

CT_IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}' || true)"
echo "GLANCE_CT_IP=${CT_IP}"
