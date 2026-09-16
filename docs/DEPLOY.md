# Running it

Four ways, in the order most people should try them. All of them serve the
same thing: `http://<host>:8080/c/<channel>.png`.

Whatever you choose, **the two directories that matter** are:

| | Holds | Back it up? |
|---|---|---|
| `config/` | `settings.yaml`, `holidays.yaml`, `vocabulary/`, your artwork | yes |
| `data/` | caches, rotation state, the `/edit` overlay | the overlay, if you use `/edit` |

Everything else is code.

---

## Docker

```bash
git clone <this repo> && cd glance-png-server
cp .env.example .env          # optional; fill in what you use
docker compose up -d
```

Then open `http://localhost:8080/preview`.

`config/` and `data/` are bind-mounted from the checkout, so you edit
`config/settings.yaml` with a normal editor and the server picks it up without
a restart. An empty `config/` is seeded from the image on first run.

Three environment variables move things about, and the image sets all three:

| | |
|---|---|
| `GLANCE_CONFIG` | path to `settings.yaml` — `holidays.yaml` and `vocabulary/` are looked for beside it |
| `GLANCE_DATA_DIR` | caches, rotation state, the overlay |
| `GLANCE_STATIC_DIR` | artwork |

Artwork is mounted from `assets/static`, the same place it lives when you run
without Docker, so the two do not quietly keep separate copies.

Built and run on `linux/arm64` (Docker 29.8 via Colima): the image comes out at
**289 MB**, starts healthy, seeds an empty `config/` on first run, writes its
caches to `data/`, and serves every route including `/preview` and `/edit`.

## Any machine with Python

Needs **Python 3.10 or newer**.

```bash
git clone <this repo> && cd glance-png-server
cp .env.example .env
./run.sh
```

`run.sh` builds the virtualenv on first run, installs the dependencies, reads
`.env`, and serves. If you would rather do it by hand:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn glance.server:app --host 0.0.0.0 --port 8080
```

That is the whole install. No database, no build step, no compiler — every
dependency ships wheels.

### As a service

`deploy/glance-png-server.service` is a systemd unit with the filesystem
locked down (`ProtectSystem`, `PrivateTmp`, a read-only root and a short list
of writable paths). Substitute the four `__PLACEHOLDER__` values and drop it
in `/etc/systemd/system/`:

```bash
sed -e "s|__ROOT__|/opt/glance-png-server|" \
    -e "s|__USER__|glance|" \
    -e "s|__HOST__|0.0.0.0|" \
    -e "s|__PORT__|8080|" \
    deploy/glance-png-server.service | sudo tee /etc/systemd/system/glance.service
sudo systemctl enable --now glance
```

## Proxmox

`deploy/pve-deploy.sh` does the whole thing from a laptop in one command:
creates an unprivileged LXC container if it is missing, installs Python,
copies the tree, writes the unit, starts it, and waits for `/healthz`.

```bash
deploy/pve-deploy.sh --pve root@proxmox --ip 192.168.1.50/24 --gw 192.168.1.1
deploy/pve-deploy.sh --pve root@proxmox          # subsequent updates
```

It excludes `.env`, the caches, the rotation state, the `/edit` overlay and
your reminders from the payload, so a redeploy never overwrites what is
running. `--dry-run` shows the tarball without changing anything.

---

# Exposing it

## On a LAN

Nothing to do. Point the device at `http://<server-ip>:8080/c/main.png` and
leave `server.access_token` empty.

If your display's setup app insists on a hostname rather than an IP, give the
server a name on your own DNS — most routers (UniFi, OPNsense, pfSense, Pi-hole,
AdGuard) can map one to a LAN address in a couple of clicks.

## On the internet

Perfectly reasonable, and the reason the token exists — but read this first.

**Set an access token.** Without one, anyone who finds the URL can read every
panel, and the calendar panels are your actual calendar.

```bash
openssl rand -hex 16        # then put it in .env as GLANCE_TOKEN
```

Every route except `/healthz` then needs `?k=<token>`, and a wrong or missing
one answers **404 rather than 403** — a stranger cannot even learn which
channels exist. Your device URL becomes
`http://host:8080/c/main.png?k=<token>`.

**Put it behind a reverse proxy.** Caddy or nginx in front gives you TLS, real
logging and somewhere to rate-limit. There is no rate limiting in this server;
it assumes something in front of it, or a network that does not need it.

**Know what `/edit` can do.** It writes config and accepts file uploads. It is
behind the same token as everything else, which is one secret protecting both
"look at my panels" and "change my panels". If that gap matters to you, keep
`/edit` off the public side at the proxy and reach it over your LAN or a VPN.

**Uploads are checked but not sandboxed.** Filenames are flattened against
path traversal, only image extensions are taken, there is a 4 MB cap, and the
content is decoded to confirm it really is an image before anything is
written. That is a reasonable bar, not a guarantee.

**A note on the device itself.** Panels like the Glance Scroll fetch over plain
HTTP, so a TLS-terminating proxy is for *your* browser and the editor, not for
the device — it will still be asking for `http://`. Do not assume the image in
transit to the panel is private.

---

# Troubleshooting

**Nothing renders / a red card.** The card says why. `curl -s
localhost:8080/api/status | jq .sources` gives the same reason per source,
including `last_error`.

**A panel is blank.** It is probably a scene that reports itself unavailable —
an empty calendar, an unconfigured source. `/api/status` lists, per channel,
which entries are currently `available`. `always: true` on an entry keeps it in
the rotation regardless.

**The panel shows something old.** The device caches the last image it
fetched, and it may not refresh more than once a minute. `/preview` shows what
the server would serve right now; if that is current and the panel is not, the
device is holding a stale copy.

**A setup app refuses your URL.** Some displays validate the URL from their own
servers when you add it, which means it has to be reachable from outside your
network at that moment, even if every fetch afterwards is local. Nothing in
this server can change that. What does work: give the server a public hostname
for as long as it takes to add, or host it somewhere already reachable.

**The container will not start (Proxmox).** The script prints `pct config`,
`pct start --debug` and the LXC log on failure. The usual causes are a
template built for the wrong architecture and `nesting=1` missing — the unit's
`PrivateTmp` and `ProtectSystem` need it on Debian 13.
