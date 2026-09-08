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
| `--dry-run` | off | package and list, send nothing |

To drop the `:8080` from the URL, deploy with `--port 80`. The systemd unit
already carries `AmbientCapabilities=CAP_NET_BIND_SERVICE`, so the non-root
service user can bind a privileged port without running as root.

### If the container will not start

`pct create` can succeed and `pct start` still fail, typically like this:

```
sync_wait: 34 An error occurred in another process (expected sequence number 7)
__lxc_start: 2126 Failed to spawn container "101"
```

The deploy script stops at that point and prints `pct config`, the tail of
`pct start --debug`, and `/var/log/lxc/<ctid>.log` — the failure is almost
always named in one of those three.

The usual cause is the **unprivileged** container: LXC maps the container's
users into a host uid range, and if AppArmor or `/etc/subuid` and
`/etc/subgid` are not cooperating, it dies during spawn. This is a known rough
edge on the **ARM builds of Proxmox** in particular.

To find out whether that is it, destroy the failed container and retry
privileged:

```bash
ssh root@proxmox 'pct destroy 101'
deploy/pve-deploy.sh --pve root@proxmox --ip 192.168.1.50/24 --gw 192.168.1.1 --privileged
```

If it starts that way, the problem was the uid mapping. A privileged container
is a weaker boundary — root inside is closer to root outside — so it is worth
fixing the mapping and going back to unprivileged if you can. For a service on
your own LAN that renders PNGs, it is a defensible place to land in the
meantime.

Note the container is created with **no `nesting` feature**. It runs a plain
Python service, never containers inside containers, and nesting only loosens
the AppArmor profile.

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

If the device is *not* on the same network as the server, you need a public
URL after all: `cloudflared tunnel --url http://localhost:8080` gives you one
free, without port forwarding. Note the device speaks plain HTTP, so a tunnel
that forces HTTPS-only may not work.

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
