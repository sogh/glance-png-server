#!/usr/bin/env bash
# Create an LXC container on a Proxmox host to run the Glance PNG server.
# Run this ON THE PROXMOX HOST as root. It is self-contained -- you can scp
# just this one file across.
#
#     IP=192.168.1.50/24 GW=192.168.1.1 bash proxmox-create-lxc.sh
#
# Every setting is an environment variable:
#     CTID       container id            (default: next free)
#     HOSTNAME   container hostname      (default: glance)
#     IP         static address + CIDR   (REQUIRED, or IP=dhcp)
#     GW         gateway                 (required unless IP=dhcp)
#     BRIDGE     network bridge          (default: vmbr0)
#     STORAGE    rootfs storage          (default: local-lvm)
#     DISK       rootfs size in GB       (default: 4)
#     CORES      cpu cores               (default: 1)
#     MEMORY     RAM in MB               (default: 512)
#     SSH_PUBKEY path to a public key    (default: the host's root key, if any)
set -euo pipefail

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
HOSTNAME="${HOSTNAME:-glance}"
BRIDGE="${BRIDGE:-vmbr0}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
DISK="${DISK:-4}"
CORES="${CORES:-1}"
MEMORY="${MEMORY:-512}"
IP="${IP:-}"
GW="${GW:-}"

command -v pct >/dev/null || { echo "error: pct not found -- run this on the Proxmox host" >&2; exit 1; }

# The Glance device stores the URL you give it. If this container's address
# moves, the panel silently keeps showing its last cached frame and looks like
# it is still working. So a static lease is the default, not an afterthought.
if [[ -z "$IP" ]]; then
  cat >&2 <<'MSG'
error: IP is required.

  The Glance device remembers the URL you configure. If this container gets a
  new DHCP address later, the panel will keep displaying its last cached image
  and look perfectly healthy while fetching nothing.

  Give it a static address outside your DHCP pool:

      IP=192.168.1.50/24 GW=192.168.1.1 bash proxmox-create-lxc.sh

  Or, if you would rather pin it by MAC reservation on your router:

      IP=dhcp bash proxmox-create-lxc.sh
MSG
  exit 1
fi

if [[ "$IP" == "dhcp" ]]; then
  NET="name=eth0,bridge=$BRIDGE,ip=dhcp"
else
  [[ "$IP" == */* ]] || { echo "error: IP needs a CIDR suffix, e.g. 192.168.1.50/24" >&2; exit 1; }
  [[ -n "$GW" ]] || { echo "error: GW is required when IP is static" >&2; exit 1; }
  NET="name=eth0,bridge=$BRIDGE,ip=$IP,gw=$GW"
fi

echo "==> finding a Debian template"
pveam update >/dev/null 2>&1 || true
TEMPLATE="$(pveam available --section system 2>/dev/null | awk '{print $2}' \
            | grep -E '^debian-1[0-9]-standard' | sort -V | tail -1)"
[[ -n "$TEMPLATE" ]] || { echo "error: no debian template found in 'pveam available'" >&2; exit 1; }

if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  echo "==> downloading $TEMPLATE"
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

SSH_ARG=()
SSH_PUBKEY="${SSH_PUBKEY:-}"
if [[ -z "$SSH_PUBKEY" && -f /root/.ssh/authorized_keys ]]; then
  SSH_PUBKEY=/root/.ssh/authorized_keys
fi
if [[ -n "$SSH_PUBKEY" && -f "$SSH_PUBKEY" ]]; then
  SSH_ARG=(--ssh-public-keys "$SSH_PUBKEY")
  echo "==> authorising ssh key(s) from $SSH_PUBKEY"
else
  echo "==> no ssh key found; set a root password with 'pct set $CTID' or use 'pct enter $CTID'"
fi

echo "==> creating container $CTID ($HOSTNAME) on $BRIDGE"
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" \
  --memory "$MEMORY" \
  --swap 512 \
  --rootfs "$STORAGE:$DISK" \
  --net0 "$NET" \
  --unprivileged 1 \
  --features nesting=1 \
  --onboot 1 \
  --start 1 \
  "${SSH_ARG[@]}"

echo "==> waiting for the container to come up"
for _ in $(seq 1 60); do
  if pct exec "$CTID" -- test -e /run/systemd/system 2>/dev/null; then break; fi
  sleep 1
done

echo "==> installing prerequisites inside the container"
pct exec "$CTID" -- bash -lc '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-dev curl rsync openssh-server ca-certificates >/dev/null
  systemctl enable --now ssh >/dev/null 2>&1 || true
'

CT_IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')"

cat <<MSG

    container $CTID is up at ${CT_IP:-<check with: pct exec $CTID -- hostname -I>}

    Next, from your Mac, in the project directory:

        CT_HOST=${CT_IP} deploy/sync.sh          # copy the code across
        ssh root@${CT_IP} 'bash /opt/glance-png-server/deploy/install.sh'

    Then point the Glance private app at:

        http://${CT_IP}:8080/c/main.png

MSG
