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

## Documentation

- **[docs/DEVICE.md](docs/DEVICE.md)** — what the Glance Scroll actually does,
  including the undocumented behaviour found by experiment
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — code map and the
  reasoning behind the non-obvious decisions
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — packaging plan and open items

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

### Why there's no clock in the default channels

The device redraws a cached image until its next fetch, so a clock is wrong
for most of the time it is on screen — which is exactly the failure you see in
Glance's own clock app, only milder. The shipped channels use `date` instead:
correct all day, no apology needed. `clock` is still there with a `lead`
parameter if you want it.

## Editing the carousel live

`/edit` is a page for changing what a channel shows, in what order, and how
long each entry stays up. Changes take effect on the panel's **next fetch** —
no restart, no redeploy.

```
http://your-host:8080/edit
```

Per entry: reorder with the arrows, toggle `enabled`, set `dwell`, mark an
entry as `takeover`, and see a live thumbnail of what it renders. Below that,
the carousel's own `mode`, clock `dwell` and `min advance`, and a file input
for artwork.

**Every scene declares its parameters**, so the editor draws real controls —
dropdowns listing the actual sprites, fonts, colours and calendars you have,
numbers with their bounds, checkboxes for flags, and each one's purpose on
hover. Before this the params were a raw JSON box, and the only way to learn
what a scene accepted was to read its source.

Only values that differ from the default are stored, so the overlay stays a
short list of decisions rather than a dump of every knob. A save reports
anything it did not recognise:

```
sprite: 'befoer' is not a parameter of sprite (known: after, always,
background, before, color, font, gap, scale, sprite, sprite_scale)
```

It still saves — a config written before the schema may legitimately carry an
extra key — but a typo is no longer silently ignored, which is what it was
before. `when` is there too, as JSON with examples, under *when / advanced*.

### It never writes to settings.yaml

Everything saves to `data/overrides.json`, which the editor exclusively owns.
`settings.yaml` is hand-authored with comments explaining why things are the
way they are; round-tripping it through a web form destroys those and
guarantees conflicts with the repo. Keeping edits in a separate file means:

- your config stays readable and version-controlled
- **reset to file** is just deleting a key
- a deploy never clobbers what you changed from the UI (`data/overrides.json`
  is excluded from the payload, along with rotation state and caches)
- every override is visible in one small file you can read or delete

A channel present in the overlay **replaces** that channel wholesale rather
than merging entry by entry — the editor always sends the full list, and
merging arrays by index is a reliable source of surprises. A corrupt overlay
is ignored rather than taking the panel down, and a save that fails validation
changes nothing.

### `dwell` — controlling the pace

This is the only way to control how fast the panel changes. **The device
decides how often it fetches**, and the floor is 60 seconds; nothing here can
make it ask more often. So "show this for five minutes" has to mean "keep
returning the same thing until five minutes have passed":

```yaml
- scene: holiday
  dwell: 300        # holiday art stays up for five minutes
- scene: agenda
  dwell: 60         # the next event turns over quickly
- scene: date
  dwell: 0          # advance on every fetch
```

`carousel.min_advance_interval` is a floor under all of it, so a double fetch
cannot burn two slots regardless of dwell.

### API

The page is a thin client over these, if you would rather script it:

| Route | |
|---|---|
| `GET /api/channels` | channel names, available scenes, carousel settings |
| `GET /api/channels/<name>` | one channel's entries, and whether it is overridden |
| `PUT /api/channels/<name>` | replace its entries (validated first) |
| `POST /api/channels/<name>/reset` | drop the overlay, restore `settings.yaml` |
| `GET /api/art` | list the artwork, with sizes |
| `POST /api/art` | upload a file (multipart) |
| `DELETE /api/art/<name>` | remove one |
| `PUT /api/carousel` | mode, dwell, min advance |

All of them require the access token when one is set.

### Two layers of cycling

The device and this server both rotate, at very different speeds, and they
compose rather than compete:

| | What rotates | How fast | Controlled by |
|---|---|---|---|
| **Device** | between private-app slots | seconds | the Glance |
| **Server** | within one channel | one refresh, 60s+ | this config |

So one private app slot pointed at one channel gives you smart, conditional
content that changes slowly. Several slots, each pointed at a **different**
channel, give you the visible scrolling effect *and* the logic:

```
slot 1 -> http://your-host:8080/c/next.png     what is coming up
slot 2 -> http://your-host:8080/c/tasks.png    what needs doing
slot 3 -> http://your-host:8080/c/art.png      your own PNGs
slot 4 -> http://your-host:8080/c/time.png     clock
```

The device flips between those four every few seconds, while each one quietly
rotates its own contents on every refresh. Ten slots is the device's limit.

The shipped `config/settings.yaml` defines exactly these four, plus a `main`
that does everything in one slot if you would rather keep it simple.

### Empty states: `always`

A scene with nothing to show drops out of its channel — that is what stops an
empty todo list serving a blank panel. In a single-purpose slot, though,
dropping out means the slot falls through to the channel fallback, which is
rarely what you want: a `tasks` slot should say "all clear", not show a clock.

`always: true` keeps an entry in the rotation regardless, letting the scene
draw its own empty state:

```yaml
tasks:
  - scene: todos
    params: { count: 3, always: true }   # draws "all clear" when empty
  - scene: todos
    params: { style: hero }              # drops out when empty
```

With todos present those two alternate. With none, the first holds the slot
and the second steps aside. Supported by `todos` and `agenda`.

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
| `today-agenda` | What's left on today's calendar | (always; says "nothing today") |
| `columns` | Three columns of upcoming events, packed by day | there's an upcoming event |
| `reminders` | Open items from `reminders.json` | anything is undone |
| `todos` | Same scene, older name | anything is undone |
| `static:<name>` | A PNG from `assets/static/` | the file exists |
| `weather` | Current conditions, high and low | coordinates are set |
| `instagram` | Follower and post counts | a Graph API token is set |
| `baseball` | Last result and next game, and where to watch | teams are configured |
| `date` | Day and date, no clock | always |
| `panels` | Test card: shows the physical 64px modules | always |
| `clock` | Time and date | always |
| `countdown` | Days until a target date | always |
| `marquee` | Scrolling text, as an animated PNG | always |
| `pulse` | Names with a colour ramp across the letters | always |
| `sprite` | Text with a pixel-art sprite set into it | always |
| `sprites` | Every sprite, for checking the art | always |
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

## How wide is your Scroll?

A Glance is built from **64x32 LED modules chained together**, and they show
**one continuous image** — a 192px display is three modules cooperating, not
three separate screens. That is a different thing from private-app slots,
which really are separate pages the device cycles between.

| | What it is | How many |
|---|---|---|
| **Panel / module** | physical 64x32 LED block | 1–6 (up to 384px) |
| **Private app slot** | a page of content | up to 10 |

So "3 panels" describes the hardware you own, and the width every image has to
be drawn at. Getting it wrong means the panel crops or squashes everything.

To check, point a slot at the test card:

```
/s/panels.png
```

It draws each 64px module with its own colour, number and pixel range, plus a
white dot in all four extreme corners. On the real display:

- **count the numbered blocks** — that is your module count
- **all four corner dots visible** — the width is right and it is 1:1
- **corners missing or text squashed** — the image is not the panel's width

`?width=` overrides the configured width for a single request, so you can try
each without editing anything:

```
/s/panels.png?width=64      one module
/s/panels.png?width=128     two
/s/panels.png?width=192     three
```

Whichever lands cleanly, set as `panel.width` in `config/settings.yaml`. The
private app's own "image width" field should match it.

## Your own artwork

Two ways in. **Upload them at `/edit`** — they land in `assets/static/` and
are usable immediately as `static:<name>`, with no redeploy. Or drop files
into `assets/static/` directly; they're picked up the same way. Files are
cached by mtime, so re-exporting over one hot-reloads the panel.

Uploads are checked before they land: the content must actually decode as an
image, 4 MB and eight-times-panel dimensions are the ceilings, and the
filename is reduced to letters, digits, dot, dash and underscore. That last
one matters more than it looks — the name becomes a path, so `../../etc/x.png`
is flattened to `x.png` and anything with shell characters is refused
outright. Writes are atomic, so a half-uploaded file is never served.

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

## Animation: the device does not do it

Tested and settled. An APNG served to a Glance Scroll renders **frame zero and
stops** — it does not animate.

That is a defensible engineering call on their side: APNG needs multi-frame
buffering, and on a chip driving LED matrices from limited RAM that is real
memory. Most small embedded PNG decoders skip it. The gap is that the docs
never say so, which is why this had to be settled by experiment.

Nothing here breaks because of it. An APNG is a valid PNG, so the panel shows
frame zero cleanly — but paying for thirty frames that will never be seen is
pointless, so the animated scenes default to a single frame now.

`marquee` and `pulse` can still emit APNG on request (`mode: pulse`), and the
preview page renders them, since browsers do animate. If a firmware update
ever changes this, the mechanism is already there.

**What still moves:** the device cycles between private-app slots on its own
clock, every few seconds. That is real motion, and it is what several channels
across several slots buys you.

### `sprite` — pixel art set into a line of text

```
/s/sprite.png?before=It%27s&sprite=sweatpants&after=season%21
```

Renders *It's [sweatpants] season!* — the art sits in the gap between the two
strings.

```yaml
- scene: sprite
  params:
    before: "It's"
    sprite: sweatpants
    after: "season!"
    color: amber          # the text; the sprite keeps its own palette
    gap: 5
  dwell: 300
```

Text is scaled to the largest whole size that fits beside the sprite, gaps
tighten on a narrow panel, and if it still will not fit the strings are
truncated in proportion rather than running off the edge. It renders correctly
down to a single 64px module.

#### Drawing a new sprite

Sprites live in `glance/sprites.py` as pixel art, the same way the fonts do —
`.` is transparent, every other character is a palette entry:

```python
MUG = Sprite(
    rows=(
        "..######..",
        ".########.",
        ".#      #.",
    ),
    palette={"#": "#8c8c91"},
)
SPRITES["mug"] = MUG
```

Tests check every sprite is a clean rectangle, that each character used has a
palette entry, and that nothing is taller than the panel — a ragged row
silently shifts everything below it.

### `pulse` — a colour ramp across the letters

```
/s/pulse.png?items=ADA:yellow,GRACE:blue
```

Since the panel cannot fade a colour over *time*, this fades it over *space*:
each name ramps from white to its own colour across its characters. The same
visual idea, in one frame, on hardware that will never animate.

```yaml
- scene: pulse
  params:
    items: "ADA:yellow,GRACE:blue"
    layout: column      # or row, side by side
    from: white         # the colour each name starts at
    mode: gradient      # `pulse` instead for the APNG version
  dwell: 300
```

`items` is a `NAME:colour` list so the same value works from a channel config,
the editor's params box and a query string alike. Any palette colour or
`#rrggbb` works, in either position — `items: "ADA:white" from: yellow` runs
the ramp the other way.

The scale is chosen to fit the panel, and an explicit `scale` that would not
fit is **clamped rather than obeyed** — a smaller name beats half a name.

`Canvas.text_gradient()` does the drawing, so any scene can use it.

## A note on stale clocks

If you have seen Glance's own clock app sit hours behind, that is the
signature of **server-side render caching**: community apps run on Glance's
infrastructure with a default 300s TTL keyed on `(url, params, headers)`, and
a clock is precisely the thing that breaks under it.

This server renders on every fetch and sends `no-store`, so it cannot go hours
out. It still cannot beat the device's own cache, though: an image fetched at
14:00 with a 300s refresh is still on the panel at 14:04.

The `clock` scene takes a `lead` for exactly this — shift the rendered time
forward by half your refresh interval so the error is centred rather than
always behind:

```yaml
- scene: clock
  params:
    lead: 150        # with refresh: 300
```

At worst 2.5 minutes out in either direction, instead of up to 5 minutes slow.

## Data sources

### Calendars

One feed per purpose reads better than one feed with everything in it:

```yaml
sources:
  calendars:
    agenda:                              # things with times on them
      url: "${GLANCE_ICS_AGENDA:-}"
      color: white
      accent: amber
    reminders:                           # things to remember
      url: "${GLANCE_ICS_REMINDERS:-}"
      accent: sky
    events:                              # birthdays, anniversaries
      url: "${GLANCE_ICS_EVENTS:-}"
      color: mint
      accent: purple
```

Each URL is Google Calendar → Settings → *your calendar* → **Secret address in
iCal format**. They are passwords; keep them in `.env`. A calendar declared
without a URL is simply skipped, so you can add them one at a time.

Scenes pick a feed with `calendar:` — one name, several comma-separated, or
omit it to merge them all:

```yaml
- scene: agenda
  params: { calendar: reminders }
- scene: agenda
  params: { calendar: "agenda,events" }
```

Recurrence is expanded locally, so weekly meetings and annual birthdays
resolve. Feeds are cached to disk and **a failed fetch serves the cached copy
rather than blanking the panel**.

The older single-feed form still works: `sources.calendar.ics_url` becomes a
calendar named `default`.

#### Styling entries

**Google's ICS export carries no colour.** No `COLOR`, no `CATEGORIES` — the
colour you pick in Google Calendar does not survive the export. The fields
that *do* export are the title, the description and the location, so that is
where styling has to live.

Per-calendar defaults in `settings.yaml` cover most of it. For a single entry,
tag it in the title — editable from your phone, and stripped before drawing:

```
Call the plumber #red          →  drawn as "Call the plumber", in red
Bin day #green #big
Dentist #urgent                →  red, priority 1
Draft notes #quiet             →  dimmed
Personal thing #hide           →  stays in the calendar, never on the panel
```

Any palette colour name works as a tag, plus `#big` / `#hero`, `#quiet`,
`#urgent`, `#hide`, `#done`.

**A `#word` that is not a known keyword is left alone** — "Pay the #1 invoice"
renders exactly as typed.

For more, or to keep the title clean, use `key: value` lines in the
description:

```
color: green
style: hero
priority: 1
```

Only `color`, `accent`, `style`, `priority`, `hidden` and `dim` are read, so
an ordinary description cannot restyle an entry by accident. Title tags beat
description keys; both beat the calendar's defaults.

### Weather

Open-Meteo, chosen because it needs **no API key and no account** — just
coordinates. One call returns current conditions and today's high and low in
under a kilobyte.

```yaml
sources:
  weather:
    latitude: "${GLANCE_LAT:-}"
    longitude: "${GLANCE_LON:-}"
    units: fahrenheit       # or celsius
    refresh: 900
```

Right-click your house in Google Maps to get the coordinates. With none set
the scene drops out of rotation rather than showing an empty box.

The temperature is coloured by value — orange above 75, blue below 45 — so it
reads from across a room before you have focused on the digits. The third line
carries the chance of rain today (or the amount, if it is actually falling)
and the **US AQI coloured by band** — green good, yellow moderate, orange,
red, purple, crimson. The colour is the point: a bare AQI number means nothing
unless you already know the scale.

Air quality is a second call to a different Open-Meteo host, cached
separately; set `air_quality: false` to skip it. If that call fails the
forecast is unaffected — the panel simply omits the AQI.

The right of the strip carries a **three-day forecast** — weekday, a 12px
icon, and the high, colour-coded the same way. Only the high: two
temperatures per 21px column is more than the space carries legibly, and the
low is the one you can do without. `forecast: 0` reclaims the room, and the
detail text expands to fill it. Icons are
drawn from primitives in `glance/weathericons.py` (clear, partly, cloudy, fog,
drizzle, rain, snow, thunder, plus a crescent moon at night), because circles
and clouds are far easier to describe as overlapping discs than to type out
pixel by pixel.

As with the calendar, a failed fetch serves the cached reading: a slightly
stale temperature beats a blank panel.

### Baseball

MLB's own Stats API (`statsapi.mlb.com`) — **no key, no account**.

```yaml
sources:
  baseball:
    teams: "SEA"          # abbreviations, comma-separated
    refresh: 600
    live_refresh: 60      # poll harder while a game is being played
```

The panel shows **the last result and the next fixture together**, because a
result stays interesting for a while after the final out and then the next
game becomes the thing you want. A game actually in progress takes the whole
strip instead — score large, inning, and where to watch.

Two details that a naive scoreboard gets wrong:

**The broadcast follows *your* team.** Every game lists feeds for both sides,
so a Mariners fan watching a road game wants `Mariners.TV`, not the home
network. Printing the first listing in the array is wrong half the time.

**A score is only drawn once one exists.** MLB reports `0 - 0` for a game in
`Pre-Game` state; rendering that makes a game that has not started look like a
scoreless one in progress. Before first pitch the panel shows the matchup and
the start time instead.

### Instagram counts

**Scraping does not work, and that is why the counts you see elsewhere are
wrong.** An unauthenticated request for a public profile returns a login wall
or `{"require_login": true}` — *intermittently*, not consistently. An app built
on it does not fail loudly; it falls back to a stale or zero value and
presents it as current.

So this uses the official Graph API, and when it cannot get a fresh number it
**says so rather than guessing**. A count openly labelled six hours old is more
useful than one that might be wrong and looks current. With no cached value at
all it explains itself instead of drawing a zero — zero followers is a number,
and showing it would be a lie.

```yaml
sources:
  instagram:
    access_token: "${GLANCE_IG_TOKEN:-}"
    account: ""          # blank = the token's own account
    refresh: 3600
```

Setup, once:

1. The account must be **Business or Creator**, linked to a Facebook Page
   (Instagram app → Settings → Account type)
2. [developers.facebook.com](https://developers.facebook.com) → create an app →
   add **Instagram Graph API**
3. Graph API Explorer → select the app and Page → request `instagram_basic`
   and `pages_show_list` → generate a token
4. Exchange it for a long-lived token (60 days) or create a **System User**
   token, which does not expire
5. `GLANCE_IG_TOKEN=...` in `.env`

Leave `account` blank for the token's own account — exact, and the simplest
thing that works. Set it to another public Business or Creator handle to use
`business_discovery` instead; that only works against Business/Creator
accounts, not personal ones.

The age appears top-right in amber once the figure passes `stale_after`
(default 6 hours). A silent panel means the number is current.

### `columns` — as much of the week as fits

```
┌──────────────────┬──────────────────┬──────────────────┐
│ TODAY            │ TODAY            │ TMRW             │
│ 7a  Feed animals │ 3p  Fence repair │ 10a Al-Anon Zoom │
│ 9a  Farmers mar… │ 6p  Dinner w/ S… │                  │
│ 11:30a Vet visit │                  │                  │
│ 1p  Deliver eggs │                  │                  │
└──────────────────┴──────────────────┴──────────────────┘
```

192 divides into three 64px columns, which is **exactly one physical LED
module each** — the layout lands on the hardware's own seams.

Days are packed greedily. A day fills its column; if it has more events than
fit, it spills into the next and pushes the following day along. Best case is
three days of a few events each; worst case is one busy day taking all three
columns, which is the right thing to show when that is what the day looks
like. A continuation column repeats the day label dimmed, so the eye does not
read it as a new day.

**`skip_columns` pairs two panels into one continuous view.** One at
`skip_columns: 0` shows columns 1–3, another at `3` shows columns 4–6 — no
overlap, no gap, *whatever* the packing does. That is the thing an offset
measured in days cannot give you: whether the near panel spilled is exactly
what decides where the far one should start. A day that straddles the
boundary simply continues into the second panel rather than restarting.

`from_days` is also there if you want a fixed "next week" window instead; it
skips whole calendar days.

**Titles wrap, but only into space nobody else wants.** Every event gets one
row; leftover rows go to titles that are still truncated, most-starved first.
So a column holding two events can give both a second line, a column holding
one can give it all four — and a full column of four wraps nothing, because
wrapping must never cost an event its slot. `wrap: false` turns it off.

**The budget:** 4 events per column, 12 in total, with roughly 10 characters
of title each — or two to four times that when a column has room to wrap. Times drop their minutes on the hour — `9a` rather than `9:00a`
— which buys ten pixels of title on half the rows, and a 64px column has none
to spare. Anything that still does not fit is counted in a `+N` badge rather
than silently dropped.

### Reminders without a calendar

`data/reminders.json` still exists for anything that does not belong on a
calendar — no date, no time, just a standing note. Re-read whenever its mtime
changes:

```json
[
  { "text": "Renew passport", "due": "2026-09-11", "priority": 1 },
  { "text": "Water the ferns", "tag": "home" },
  "a bare string also works"
]
```

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

> **First time?** Run `ssh-copy-id root@proxmox` once and deploys are silent.
> Without a key you get exactly one password prompt: every step shares a single
> multiplexed connection rather than opening four.

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
