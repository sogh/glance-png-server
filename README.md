# glance-png-server

A private-app server for the **Glance Scroll**. It serves PNGs at a URL the
device polls — mixing artwork you drew by hand with panels generated from live
data (calendar, todos, holidays), and rotating between them on a single
endpoint.

```
┌────────────────────────────────────────────────────────┐
│  9:30  │ Team standup                                  │   192 × 32
│  AM    │ ZOOM                                          │   ~300 bytes
│  TODAY │                                               │
└────────────────────────────────────────────────────────┘
```

---

## What the device actually requires

From the [Glance developer docs](https://glance-led.dev/docs/private-apps/):

| Constraint | Value |
|---|---|
| Canvas height | **always 32px** |
| Canvas width | 1–384px (64px panel modules); **192×32 recommended** |
| Format | **PNG only** — JPEG is not decoded |
| Colour | full RGB (name, `#hex`, or `(r,g,b)`) |
| Transport | plain HTTP `GET` — **HTTPS is not supported**; no file extension needed |
| Who fetches | **the device itself, over your own network** — not Glance's servers |
| Response size | **1 MB** cap |
| Request timeout | **~4 seconds** |
| Refresh interval | 60s practical minimum, **300s default** |
| Private apps per device | 10 |

The device caches the image it fetched and redraws that between refreshes, so
it only hits your server once per interval.

The device does its own fetching — *"Your Glance fetches that image directly
over your own network and caches it on the device itself."* Glance's servers
only store the URL string so the device knows where to look; the image is never
uploaded to, stored on, or proxied through them. **That means a LAN address
works and no tunnel is needed**, as long as the device and the server are on
the same network.

Traffic is unencrypted and the URL is stored on Glance's servers, so treat
anything the panel displays as public. Don't put on it what you wouldn't post.

Typical frames here come out at **150–600 bytes**, roughly 0.05% of the cap.

---

## Quick start

```bash
git clone <this> && cd glance-png-server
cp .env.example .env          # add your calendar URL (optional)
./run.sh                      # creates the venv, installs deps, serves
```

Then open **http://127.0.0.1:8080/preview** — every scene and channel rendered
at 4× with pixel-exact scaling, auto-refreshing every 10s. That page is where
you'll do most of your design work.

Point your Glance private app at:

```
http://<your-public-host>/c/main.png
```

---

## How the carousel works

The device fetches one URL. This server decides what that URL returns.

A **channel** is an ordered list of entries in `config/settings.yaml`:

```yaml
channels:
  main:
    - scene: holiday          # pre-empts everything while active
      takeover: true
    - scene: agenda
      params: { count: 1 }
    - scene: todos
      params: { count: 3 }
    - scene: static:winter-cabin
    - scene: clock
      when:
        hours: { from: 7, to: 22 }
```

Each fetch advances to the next entry. Three rules make it behave:

1. **Empty scenes drop out.** An entry whose scene reports nothing to show —
   no open todos, no upcoming events, a missing art file — is skipped entirely
   rather than serving a blank panel.
2. **`takeover: true` pre-empts the rotation** while that entry has content,
   without disturbing where the rotation had got to. Christmas morning owns the
   panel; on the 27th you resume exactly where you left off.
3. **Rotation tracks the scene, not an index.** Reordering a channel doesn't
   make the sequence jump to a random position.

Rotation state persists to `data/state.json`, so a restart doesn't reset it.

### The two modes

- **`advance`** (default) — steps on each real fetch. Fetches closer together
  than `min_advance_interval` (default 30s) return the same scene, so a device
  retry or a browser tab can't silently skip a frame nobody saw.
- **`clock`** — the scene is a pure function of wall-clock time. Stateless and
  identical across restarts, but can skip entries when the device's refresh
  interval and `dwell` don't line up.

---

## Scenes

| Scene | Shows | Available when |
|---|---|---|
| `holiday` | Active holiday, generated card or your own art | a holiday window is open |
| `agenda` | Next calendar event(s) | there's an upcoming event |
| `todos` | Open items from `todos.json` | anything is undone |
| `static:<name>` | A PNG from `assets/static/` | the file exists |
| `clock` | Time and date | always |
| `countdown` | Days until a target date | always |
| `text` | Fixed text from config | always |
| `blank` | A deliberately dark panel | always |

Any scene can be pinned directly for testing, with params as query string:

```
/s/clock.png?hour24=true
/s/countdown.png?date=2026-12-25&label=XMAS
/s/text.png?text=BACK+SOON&color=amber
/s/static:winter-cabin.png
```

---

## Your own artwork

Drop PNGs into `assets/static/`. They're addressable immediately as
`static:<filename-without-extension>` — no restart, no registration. Files are
cached by mtime, so re-exporting from Photoshop hot-reloads the panel.

**Export at exactly 192×32.** Oversized art is downscaled nearest-neighbour
(blocky but honest) rather than smoothly resampled — a bilinear shrink to 32px
produces grey soup on an LED matrix. Undersized art is centred, never
stretched.

### Designing for a 32px LED strip

The docs put it well: *"a photo shrunk to 32 pixels turns to mush; a chunky
icon and large text look great."*

- **Pure black is free.** Black = LEDs off. Use it as the background always.
- **Avoid very dark greys.** Channel values below ~12 sit at the bottom of the
  panel's PWM range where it bands and flickers. `palette.snap()` pushes them
  to true black automatically.
- **Full white blooms.** The built-in `white` is deliberately `(230,230,230)`.
  `hotwhite` is there if you really want 255.
- **No anti-aliasing, no gradients across small shapes.** Every edge should
  land on a pixel boundary.
- **Saturated primaries read best** at a glance from across a room.

---

## Data sources

### Calendar (Google Calendar or any ICS publisher)

Google Calendar → Settings → *your calendar* → **Secret address in iCal
format**. Put it in `.env`:

```
GLANCE_ICS_URL=https://calendar.google.com/calendar/ical/.../basic.ics
```

That URL is a password — anyone holding it can read the whole calendar. It's
kept out of `settings.yaml` and `.gitignore`d for that reason.

Recurrence rules are expanded locally, so weekly standups and annual birthdays
resolve correctly. The feed is fetched on `sources.calendar.refresh` (default
900s) and cached to disk — **if the fetch fails, cached events are served
rather than letting the panel go blank.**

### Todos

`data/todos.json`, re-read whenever its mtime changes (no restart):

```json
[
  { "text": "Renew passport", "due": "2026-09-11", "priority": 1 },
  { "text": "Water the ferns", "tag": "home" },
  "a bare string also works"
]
```

`priority` 1–3 sets the colour of the left stripe. Items sort overdue-first,
then by due date. Malformed JSON keeps the last good list rather than blanking
the panel.

### Holidays

`config/holidays.yaml`. Three ways to pin a date:

```yaml
- name: Christmas
  date: "12-25"                             # fixed month-day
  window: 14                                # start showing 14 days out
  after: 1                                  # keep showing 1 day after
  color: green
  accent: red
  countdown: true                           # "IN 5 DAYS" during the lead-up
  # image: christmas                        # use your own art instead

- name: Thanksgiving
  rule: { nth: 4, weekday: thu, month: 11 } # nth weekday (-1 = last)

- name: Good Friday
  rule: { easter_offset: -2 }               # days relative to Easter Sunday
```

Windows spanning the year boundary work — New Year's Day resolves correctly
from late December.

---

## Endpoints

| Route | Purpose |
|---|---|
| `GET /c/<channel>.png` | **What the device points at.** Advances the rotation. |
| `GET /c/<channel>.png?peek=1` | Same frame without consuming a slot |
| `GET /s/<scene>.png` | One specific scene; query string becomes params |
| `GET /preview` | All scenes and channels at 4×, auto-refreshing |
| `GET /api/status` | Why a scene is or isn't showing; source errors |
| `POST /api/reset/<channel>` | Rewind a rotation to its first entry |
| `GET /healthz` | Liveness |

Image responses carry `X-Glance-Scene` and `X-Glance-Position` headers, which
make `curl -I` a fast way to see what the device just got. Everything is sent
`no-store` — any cache in front of this would freeze the carousel on one frame.

**A broken scene renders an error card at HTTP 200, never a 500.** The device
caches its last successful fetch, so a 5xx is invisible — the panel just keeps
showing a stale frame and looks like it's working.

---

## Command line

```bash
tools/render.py clock                     # ASCII preview in the terminal
tools/render.py todos --png out.png       # write a 6× PNG
tools/render.py --channel main            # what the device would get next
tools/render.py --all --dir frames/       # every scene, for a design pass
tools/render.py holiday --at 2026-12-25   # pretend it's another day
tools/render.py text -p text=HELLO -p color=amber
```

`--at` is the one to remember: it's how you check a holiday card in September.

---

## Deploying to Proxmox

The device fetches over your LAN, so the container just needs a **static IP**
and an open port. No tunnel, no port forwarding, no certificate.

Everything runs from your Mac over **one SSH hop to the Proxmox host**. Inside
the container the work happens through `pct exec` and `pct push`, so the
container never needs `sshd`, authorised keys, or to be reachable from your
laptop at all.

```bash
# first time -- creates the container, installs, starts it
deploy/pve-deploy.sh --pve root@proxmox --ip 192.168.1.50/24 --gw 192.168.1.1

# every time after -- finds the container by name and updates it
deploy/pve-deploy.sh --pve root@proxmox
```

That's the whole deployment. The script is idempotent: same command to create
and to update, so it doubles as the art loop — export a PNG into
`assets/static/`, run it again, done.

> **The static IP is required, not a suggestion.** The Glance stores the URL
> you give it. If the container's address later changes, the panel keeps
> redrawing its last cached frame and looks perfectly healthy while fetching
> nothing. The script refuses to create a container without `--ip`.
> (`--ip dhcp` is there if you'd rather pin it by MAC reservation instead.)

Then point the Glance private app at the URL it prints — GLANCE Setup App →
*Apps* → *Private Apps* → *+*:

```
http://192.168.1.50:8080/c/main.png
```

Set the refresh to 300s (60s is the floor). With four scenes in rotation that
cycles the whole set in 20 minutes.

### What it does

1. Packages the project locally, excluding `.venv`, `.git`, `.env`, and the
   container's own runtime state.
2. `scp`s that to the Proxmox host.
3. On the host: creates an unprivileged Debian LXC if one isn't there
   (1 core / 512 MB / 4 GB, newest Debian template, downloaded if missing),
   then `pct push`es the code in and runs `install.sh` inside it.
4. `install.sh` creates a `glance` system user, builds the venv, writes a
   hardened systemd unit, enables it at boot, and waits for `/healthz` to
   answer before reporting success.

It **never** ships `data/state.json`, `data/cache/` or `.env`, and only ships
`data/todos.json` with `--with-data`. Those belong to the server — copying a
stale rotation position or ICS cache back over the top would rewind the
carousel and could serve yesterday's calendar.

`--dry-run` prints the exact file list and sends nothing.

### Options

| Flag | Default | |
|---|---|---|
| `--pve USER@HOST` | *required* | Proxmox host to ssh to |
| `--ctid N` | found by name, else next free | container id |
| `--name NAME` | `glance` | container hostname |
| `--ip A.B.C.D/NN` | *required when creating* | static address, or `dhcp` |
| `--gw A.B.C.D` | *required with static ip* | gateway |
| `--bridge` / `--storage` | `vmbr0` / `local-lvm` | |
| `--disk` / `--cores` / `--memory` | `4` / `1` / `512` | GB / cores / MB |
| `--port N` | `8080` | see below |
| `--timezone TZ` | from `settings.yaml` | container clock |
| `--with-data` | off | also push `data/todos.json` |
| `--privileged` | off | privileged container — fallback, see below |
| `--features LIST` | `nesting=1` | `pct` features |
| `--dry-run` | off | package and list, send nothing |

To drop the `:8080` from the URL, deploy with `--port 80`. The systemd unit
already carries `AmbientCapabilities=CAP_NET_BIND_SERVICE`, so the non-root
service user can bind a privileged port without running as root.

### If the setup app rejects the URL

Adding a private app runs a verification step the developer docs do not
describe. It can fail on a LAN address with:

```
image verification failed. DNS resolve failed for 192.168.1.50
```

A literal IPv4 address needs no DNS to resolve, so that message is really
saying *something in the verification path cannot reach RFC1918 space*. The
likeliest reason is that the check runs on Glance's servers rather than on the
device — blocking requests to private ranges is standard SSRF protection on
any cloud service, and it commonly surfaces as a resolution error. The device
itself would still fetch the image over your LAN quite happily afterwards.

**First, rule out the boring cause.** Open `http://<ip>:8080/preview` in a
browser *on your phone*, on the same wifi. If that fails, the phone is on
cellular or a guest VLAN and nothing else here matters. If it works and the
setup app still refuses, the check is not coming from the phone.

**Then try a publicly resolvable alias.** `nip.io` and `sslip.io` are wildcard
DNS services that resolve `<any-ip>.nip.io` to that IP — including private
ones. Public DNS resolution succeeds while the connection still happens
entirely on your LAN:

```
http://192.168.1.50.nip.io:8080/c/main.png
```

Verified against Google, Cloudflare and Quad9: `192.168.1.50.nip.io` resolves
to `192.168.1.50` from all three. This fixes the problem **if** verification
only resolves the name. If it also fetches the image, it will still fail —
their server will resolve the alias to a private address it cannot reach.

Relying on a free DNS service is a mild dependency: if it is down, the device
gets a resolution failure and keeps showing its cached frame until it
recovers. An `A` record on a domain you own, pointing at the LAN address, is
the durable version of the same trick.

In practice this alias **does not work**, and the second error says why:

```
Image verification failed. host resolves to a private/reserved IP - refused
```

The verifier resolves the name and then inspects the resulting address,
rejecting private and reserved ranges. That is ordinary SSRF protection and
the right call on their side — a server that fetches user-supplied URLs can
otherwise be pointed at cloud metadata endpoints or internal services and used
as a proxy into its own network. It simply contradicts the documentation's
claim that a Raspberry Pi on your own network works.

Two ways forward.

**Split-horizon DNS — keeps the image on your LAN.** Give a name you control
two different answers depending on who asks:

| Asker | Resolver | Answer |
|---|---|---|
| Glance's verifier | public DNS | a public address (passes the check) |
| your Glance device | your router / Pi-hole / Unbound | `192.168.1.50` |

The device uses your LAN's resolver, so it connects locally and the image
never leaves your network. Whether this holds depends on whether verification
stops at resolution or goes on to fetch — if it fetches, the public address
has to actually serve a valid PNG at that moment. Needs a domain you control
and a local resolver you can add overrides to.

**A plain-HTTP public URL — guaranteed, with a privacy cost.**

Mind the protocol here. The docs are explicit:

> "Your Glance fetches its images over plain `http` rather than `https`. This
> is a deliberate design choice."

So `cloudflared tunnel --url ...` is a poor fit despite being the obvious
reflex: it hands you an `https://` hostname and redirects HTTP to HTTPS, which
an HTTP-only client cannot follow. A quick tunnel may satisfy the *verifier*
and then fail at the *device*. If you want a tunnel, it has to be a named one
on a domain you control with "Always Use HTTPS" turned off — at which point a
port forward is simpler.

A port forward on the gateway is plain HTTP end to end and just works:

```
WAN :8080  ->  192.168.1.50:8080
```

Weigh it properly. A public URL means the panel's contents are genuinely
public. Fine for holiday artwork; a real consideration for calendar entries
and todos. The Glance docs already say to treat anything on the display as
readable by a stranger, but a LAN-only URL made that mostly theoretical and a
port forward does not.

If you go this way, **set an access token** (below), and consider pointing the
Glance at a channel carrying only non-sensitive scenes while calendar and todo
channels stay on LAN-only URLs.

### Split-horizon on a UniFi gateway

UniFi gateways can answer a hostname with a LAN address while public DNS
answers the same name with your WAN address. That gets the URL past
verification while the device still fetches locally.

**1 — a hostname.** Any domain you control works. Without one, a free dynamic
DNS name (DuckDNS and similar) does the job, since all the public record needs
to be is *not private*.

```
glance.example.com   A   <your WAN address>      (public DNS)
```

**2 — the local override.** In UniFi Network, add a local DNS A record
pointing the same name at the container:

```
glance.example.com   A   192.168.1.50           (UniFi local DNS)
```

Ubiquiti moves this between releases — recent versions have it under
*Settings → Routing → DNS*, and per-client under *Client Devices → the device
→ Settings → Local DNS Record*. See
[UniFi DNS Records and Local Hostnames](https://help.ui.com/hc/en-us/articles/15179064940439-UniFi-DNS-Records-and-Local-Hostnames).

**3 — make sure the Glance actually asks your gateway.** This is the step that
quietly breaks it. Local records only apply to clients resolving *through* the
gateway. Devices handed DNS by its DHCP do that by default, but plenty of IoT
hardware ignores the offer and hardcodes a public resolver. If the panel never
loads, that is the first thing to check — a UniFi firewall rule redirecting
outbound port 53 to the gateway forces the issue.

**4 — getting past verification.** If the check only resolves the name, the
public `A` record alone is enough. If it also fetches, briefly forward
`WAN:8080 → 192.168.1.50:8080`, add the private app, then remove the forward.
The URL is stored once; the device resolves it locally from then on.

That last step assumes verification happens only when adding an app. If Glance
ever re-verifies, the entry would break and the forward would have to stay —
at which point set an access token.


### Access token

Optional, and pointless on a LAN-only deployment. Worth setting the moment the
server is reachable from the internet.

```bash
openssl rand -hex 16          # put it in .env as GLANCE_TOKEN
```

`config/settings.yaml` already reads it:

```yaml
server:
  access_token: "${GLANCE_TOKEN:-}"
```

Every image, preview and status route then requires `?k=<token>` (or an
`X-Glance-Token` header). The device URL becomes:

```
http://your-tunnel-host/c/main.png?k=<token>
```

A wrong or missing token answers **404, not 403** — a stranger should not be
able to enumerate your channels. `/healthz` stays open so uptime checks work,
but stops listing channel names. The token is stripped before query parameters
reach a scene, so it can never end up rendered onto the panel.

This is a shared secret over plain HTTP, and the Glance speaks only HTTP — so
treat it as *raising the bar against a stranger guessing your URL*, not as
real transport security. Anyone who can watch the traffic sees the token.

### If the container will not start

`pct create` can succeed and `pct start` still fail. The deploy script stops
there and prints `pct config`, the tail of `pct start --debug`, and
`/var/log/lxc/<ctid>.log` — the real cause is almost always named in one of
those three. Read to the bottom of the debug output; the interesting line sits
just above the generic `sync_wait` / `Failed to spawn` pair.

**`Exec format error - Failed to exec "/sbin/init"`** means the template's
architecture does not match the host — an arm64 rootfs on an x86_64 kernel, or
the reverse. The container can never start. Destroy and redeploy:

```bash
ssh root@proxmox 'pct destroy 101'
deploy/pve-deploy.sh --pve root@proxmox --ip 192.168.1.50/24 --gw 192.168.1.1
```

The script selects the template matching `dpkg --print-architecture` on the
host, and refuses to reuse an existing container whose `arch:` disagrees.

**AppArmor or uid-mapping errors** point at the unprivileged container: LXC
maps container users into a host uid range, and if AppArmor or `/etc/subuid`
and `/etc/subgid` are not cooperating it dies during spawn. To test that
theory, retry with `--privileged`. If it starts that way, the uid mapping was
the problem. A privileged container is a weaker boundary — root inside is
closer to root outside — so prefer fixing the mapping and going back.

**On `nesting`:** the container is created with `features=nesting=1`, and it
matters more than the name suggests. Debian 13 ships systemd 257, which
Proxmox warns needs nesting in an unprivileged container, and this project's
own service unit uses `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome` and
`PrivateDevices` — all mount-namespace operations that fail to set up without
it. Override with `--features` only if you know you want to.

### Operating it

```bash
ssh root@proxmox "pct exec 150 -- systemctl status glance-png-server"
ssh root@proxmox "pct exec 150 -- journalctl -u glance-png-server -f"

curl -s http://192.168.1.50:8080/api/status | python3 -m json.tool
curl -I http://192.168.1.50:8080/c/main.png     # X-Glance-Scene: what it just served
```

If the panel looks frozen, `/api/status` is the first stop — it reports which
scenes are available, the last calendar error, and where the rotation is.

**Firewall:** if you run the Proxmox firewall, allow inbound TCP on your port
to the container. Nothing outbound is needed except the calendar fetch. The
Glance also has to be on the same network/VLAN — if your IoT devices are
segmented off, you'll need a rule between the two.

### Other hosts

`deploy/install.sh` works on any Debian/Ubuntu box on its own — a Raspberry Pi
on the same network is explicitly blessed in the Glance docs. Copy the project
across however you like, then `sudo bash deploy/install.sh`. On macOS, use
`deploy/com.glance.pngserver.plist.example` (a launchd agent) instead.

If the device is *not* on the same network as the server, you need a publicly
reachable URL — and it has to be **plain HTTP**, because that is all the device
speaks. A port forward on your router is the straightforward answer. A quick
`cloudflared` tunnel is not: it gives you an `https://` hostname that redirects
HTTP to HTTPS, which an HTTP-only client cannot follow. Set an access token on
anything you expose this way.

## Adding a scene

Scenes are a render function and an availability check:

```python
# glance/scenes/weather.py
from ..canvas import Canvas
from .base import RenderContext, register

def _available(ctx, params) -> bool:
    return True

@register("weather", available=_available, description="Current conditions")
def render_weather(ctx: RenderContext, params) -> Canvas:
    c = ctx.canvas()
    c.clear("black")
    c.text(2, 2, "62°", "amber", "5x7", scale=2)
    c.text(2, 20, "PARTLY CLOUDY", "sky", "3x5")
    return c
```

Import it in `glance/scenes/__init__.py` and it's addressable as
`/s/weather.png` and usable in any channel. Do network I/O in a
`glance/sources/` module with its own cache — scenes should render from data
they're handed, and must finish well inside the device's ~4s timeout.

### Canvas API

```python
c.clear("black")
c.text(x, y, "Hello", "amber", "5x7", align="center", max_width=180, scale=2)
c.text_block(x, y, ["line one", "line two"], font="3x5", leading=2)
c.centered("Big", "green", "5x7", scale=2)      # h/v centred
c.fill_rect(x, y, w, h, "red");  c.rect(...);  c.hline(...);  c.vline(...)
c.fit(pil_image)                                # nearest-neighbour, no stretch
c.to_png()  /  c.scaled(4)  /  c.to_ascii()
```

### Fonts

Three built-in bitmap fonts, no font files: **`5x7`** (full printable ASCII,
proportional), **`3x5`** (uppercase + digits, for dense rows), and
**`5x7mono`** (fixed advance — use it for clocks and counters so the layout
doesn't jitter as digits change).

`scale=N` multiplies glyphs by a whole number of pixels, the only way to
enlarge type here that keeps every edge on a pixel boundary.

Glyphs are hand-authored pixel art in `glance/fonts.py` — `'#'` lit, `'.'`
dark, rows separated by `/`. Tweaking a letter means editing the string.
(Lowercase `g` and the digit `9` are inherently close at 5px wide; the `g` uses
an x-height bowl and a left-hooking tail to separate them as much as the cell
allows. Edit to taste.)

---

## Tests

```bash
.venv/bin/python -m pytest -q      # 116 tests, <1s
```

Covers the parts that run unattended and fail silently: Easter and nth-weekday
maths, holiday windows across the year boundary, ICS recurrence and timezone
conversion, stale-cache fallback, carousel rotation and takeover semantics, and
that every endpoint returns a valid 192×32 PNG even when a scene throws.

---

## Layout

```
glance/
  canvas.py       drawing surface, PNG encoding
  fonts.py        bitmap glyph tables + text layout
  palette.py      LED-safe colours, PWM floor snapping
  carousel.py     which scene this fetch gets
  config.py       settings.yaml loading
  runtime.py      composition root
  server.py       FastAPI routes + preview page
  scenes/         one module per scene type
  sources/        ICS, todos, holidays
config/           settings.yaml, holidays.yaml
assets/static/    your PNGs
data/             todos.json, rotation state, ICS cache
tools/render.py   CLI renderer
deploy/
  pve-deploy.sh     run on your Mac: the whole deployment, one command
  _remote-pve.sh    runs on the Proxmox host; drives pct, called by the above
  install.sh        runs in the container: venv + systemd service
  glance-png-server.service            hardened systemd unit template
  com.glance.pngserver.plist.example   launchd agent, for macOS instead
```
