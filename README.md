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
| Transport | plain HTTP `GET`, public URL, no file extension needed |
| Response size | **1 MB** cap |
| Request timeout | **~4 seconds** |
| Refresh interval | 60s practical minimum, **300s default** |
| Private apps per device | 10 |

The device caches the image it fetched and redraws that between refreshes, so
it only hits your server once per interval. **Everything this server emits is
public** — the docs are explicit that you should treat any image on a Glance as
readable by a stranger. Don't put anything on it you wouldn't post publicly.

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

## Exposing it to the device

The Glance fetches over the public internet, so the server needs a public URL.

**Cloudflare Tunnel** (no port forwarding, free):

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8080
# prints https://something.trycloudflare.com -> use /c/main.png on that host
```

For a stable hostname, create a named tunnel against a domain you control.
**Tailscale Funnel** works too if you'd rather stay in that ecosystem.

### Keeping it running

`deploy/com.glance.pngserver.plist.example` is a launchd agent for macOS —
edit the three absolute paths, copy to `~/Library/LaunchAgents/`, then
`launchctl load`. Logs land in `logs/`.

---

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
```
