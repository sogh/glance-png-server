# Configuration reference

Every key in `config/settings.yaml`, every environment variable, and every
file the server reads or writes.

Two layers, and they never mix:

| | `config/settings.yaml` | `data/overrides.json` |
|---|---|---|
| Edited by | you, in an editor | the `/edit` page |
| Holds | everything | channels and carousel only |
| Survives a deploy | it *is* the deploy | yes — `data/` is excluded |
| Wins | — | **this one** |

`settings.yaml` is hand-authored and full of comments explaining why things
are as they are. Round-tripping it through a web form destroys those, so the
editor writes a separate JSON file layered on top. A channel present in the
overlay **replaces** that channel wholesale rather than merging entry by
entry — the editor always sends the full list, and merging arrays by index is
a reliable source of surprises. "Reset to file" is deleting a key.

Secrets are never in either. They live in `.env`, which is gitignored and
excluded from deploys, and are referenced as `"${NAME:-}"`.

---

## `timezone`

IANA name, e.g. `America/Los_Angeles`. Everything that renders a date or a
time uses it. No default worth relying on — set it.

## `panel`

| Key | Default | Means |
|---|---|---|
| `width` | `192` | Panel width in pixels. A Glance Scroll is 64px modules daisy-chained: 64, 128, 192. Height is always 32 and is not configurable. |
| `quantize_png` | `true` | Palette-encode the PNG. Typically 300–3000 bytes instead of tens of kilobytes, which matters against the device's 1 MB cap and ~4s timeout. |
| `logo_size` | `16` | How large team crests are drawn on `rankings`. 14 is about the floor — below it the detailed ones collapse into noise. |
| `brightness` | see below | Time-of-day dimming, applied to every finished panel. |

### `panel.brightness`

An LED matrix at full output in a dark room is unpleasant, and doing this
centrally means no scene has to think about it.

```yaml
panel:
  brightness:
    floor: 0.05             # never go darker than this
    schedule:
      - { at: "06:00", level: 0.15 }
      - { at: "07:30", level: 1.00 }
      - { at: "20:00", level: 1.00 }
      - { at: "22:00", level: 0.45 }
      - { at: "23:30", level: 0.22 }
```

The level ramps linearly between points and wraps through midnight, so it
never visibly steps while you are looking at it. Note the 20:00 point: without
it the level would ramp from breakfast to bedtime and noon would come out
dimmer than dawn.

`brightness: false` switches it off. A plain number pins it. `?brightness=1`
on any image URL overrides it for that request, which is how the preview page
shows artwork at full output.

## `server`

| Key | Default | Means |
|---|---|---|
| `host` | `0.0.0.0` | Bind address. |
| `port` | `8080` | Bind port. |
| `access_token` | empty | When set, every image, preview and status route needs `?k=<token>`. A wrong or missing one answers **404, not 403**, so a stranger cannot enumerate your channels. Leave empty on a LAN-only deployment; set it if the server is reachable from the internet. |

## `carousel`

| Key | Default | Means |
|---|---|---|
| `mode` | `advance` | `advance` steps on each real fetch. `clock` makes the scene a pure function of wall-clock time — stateless and identical across restarts, but can skip entries when the device's refresh and `dwell` do not line up. |
| `dwell` | `300` | Seconds per scene. `clock` mode only. |
| `min_advance_interval` | `30` | Two fetches closer together than this return the same scene rather than advancing twice. Stops a device retry, a browser tab or an uptime check from silently skipping a frame nobody saw. The device refreshes at most once a minute, so this sits well below 60 without ever blocking a real fetch. |

## `fallback`

```yaml
fallback:
  scene: date
```

Shown when nothing in a channel has anything to display.

## `paths`

All relative to the project root unless absolute. You rarely need these; they
exist so a package can put state somewhere else.

| Key | Default | Holds |
|---|---|---|
| `overlay_file` | `data/overrides.json` | What `/edit` saves. |
| `state_file` | `data/state.json` | Carousel rotation position. |
| `cache_dir` | `data/cache` | Fetched calendars, weather, scores, logos. |
| `static_dir` | `assets/static` | Uploaded and hand-made artwork. |
| `holidays_file` | `config/holidays.yaml` | Holiday definitions. |
| `vocabulary_dir` | `config/vocabulary` | Language decks, one file per language. |

## `modes`

A calendar event that changes what the panels show, for as long as it runs.
See [the README](../README.md#modes--a-calendar-event-that-changes-what-the-panels-show).

```yaml
modes:
  visitors:
    match: ["#visitors", "open house"]   # defaults to the mode's own name as a tag
    calendars: agenda,events             # optional; omit to watch all
    enabled: true
```

## `sources`

### `sources.calendars`

One named calendar per purpose. Each gets default styling here; individual
entries override it with `#tags`.

```yaml
sources:
  calendars:
    agenda:
      url: "${GLANCE_ICS_AGENDA:-}"   # Google: Settings → calendar → secret iCal address
      color: white                    # the event title
      accent: amber                   # the badge and rules
      refresh: 900                    # seconds between fetches
```

`sources.refresh` (default `900`) and `sources.lookahead_days` (default `14`)
set the fallback for all of them. A single `sources.calendar.ics_url` still
works and becomes a calendar named `default`.

### `sources.weather`

```yaml
sources:
  weather:
    latitude: "${GLANCE_LAT:-}"
    longitude: "${GLANCE_LON:-}"
    units: fahrenheit       # or celsius
    refresh: 900
    air_quality: true              # show an AQI at all
    air_quality_source: airnow     # airnow | open-meteo
    airnow_api_key: "${GLANCE_AIRNOW_KEY:-}"   # optional
    aqi_max_distance_km: 25
```

Weather itself is Open-Meteo — no key, no account.

**The AQI is a separate question.** Open-Meteo derives it from the CAMS
atmospheric model on a grid roughly 11km across, so it describes the air over
a region rather than a place. Measured against the nearest EPA monitor it read
**53 where the instrument said 42** — twelve points is cosmetic, but it moved
the panel from "Good" to "Moderate", which is the part anyone actually reads.

So `air_quality_source: airnow` asks EPA AirNow first and keeps the model as
the fallback, and a reading records which it was (`/api/status` reports the
station and its distance). With no `airnow_api_key` it uses the undocumented
endpoint behind airnow.gov — works, no signup, could change without notice. A
free key from airnowapi.org switches it to the documented API.

`aqi_max_distance_km` matters more than it looks. AirNow returns the closest
reading **for each pollutant separately**, from whatever station happens to
have one — here that is PM2.5 from 13km away, PM10 from 27km and ozone from
43km. The EPA's AQI is the worst of them, so applying that rule unfiltered
lets a reading from the next county describe your garden. Distance is applied
first, then the worst-of rule among what is left.

### `sources.scoreboards`

Named boards, each becoming a `scores` (and for ESPN, a `rankings`) panel.

```yaml
sources:
  scoreboards:
    ncaa:
      provider: espn                      # espn | mlb | wpbl
      league: football/college-football   # espn only
      teams: "UGA"
      top: 0                              # espn only: also follow the poll's top N
      poll: ap                            # ap | usa | fcs
      label: UGA
      refresh: 900
      live_refresh: 60
      poll_refresh: 21600
      enabled: true
```

### `sources.baseball`

MLB via statsapi, used by the older bespoke `baseball` scene and wrapped by
`provider: mlb`.

```yaml
sources:
  baseball:
    teams: "SEA"
    refresh: 600
    live_refresh: 60
```

### `sources.homeassistant`

```yaml
sources:
  homeassistant:
    url: "${GLANCE_HA_URL:-}"
    token: "${GLANCE_HA_TOKEN:-}"
    refresh: 60
```

### `sources.instagram`

```yaml
sources:
  instagram:
    account: your_account
    user_id: "${GLANCE_IG_USER_ID:-}"
    access_token: "${GLANCE_IG_TOKEN:-}"
    refresh: 3600
```

### `sources.reminders_file`

```yaml
sources:
  reminders_file:
    path: data/reminders.json
```

Non-time-anchored reminders, for anything that does not belong on a calendar.

## `channels`

One channel per private-app slot. Each is a list of entries the carousel
rotates through.

```yaml
channels:
  main:
    - scene: holiday
      takeover: true          # pre-empt the rotation while this is available
    - scene: agenda
      params: { count: 1 }
      dwell: 300              # hold this one for 5 minutes before advancing
      when: { hours: { from: 7, to: 22 } }
    - static: winter          # shorthand for scene: "static:winter"
```

| Key | Means |
|---|---|
| `scene` | Scene id — see [SCENES.md](SCENES.md). |
| `static` | Shorthand for `scene: static:<name>`. |
| `params` | Scene parameters. Unrecognised top-level keys are treated as params too. |
| `takeover` | Pre-empts the rotation while available, without disturbing where the rotation had got to. |
| `when` | `months`, `weekdays`, `hours` (list or `{from,to}`, wrapping midnight), `dates` (`"MM-DD"`), `from`/`to` (`"HH:MM"`), `mode`, `not_mode`. |
| `dwell` | Seconds to hold before advancing. The only way to control pace — the device's refresh interval is not ours to set. |
| `enabled` | `false` parks an entry without deleting it. |

---

## Environment variables

Everything in `settings.yaml` can interpolate `"${NAME:-default}"`. These are
the ones the shipped config expects. Put them in `.env` — gitignored,
`chmod 600`, and excluded from the deploy payload.

| Variable | Used by |
|---|---|
| `GLANCE_ICS_AGENDA` | the `agenda` calendar |
| `GLANCE_ICS_REMINDERS` | the `reminders` calendar |
| `GLANCE_ICS_EVENTS` | the `events` calendar |
| `GLANCE_LAT`, `GLANCE_LON` | weather |
| `GLANCE_HA_URL`, `GLANCE_HA_TOKEN` | Home Assistant |
| `GLANCE_IG_USER_ID`, `GLANCE_IG_TOKEN` | Instagram |
| `GLANCE_TOKEN` | `server.access_token` |
| `GLANCE_CONFIG` | path to an alternative `settings.yaml` |

A Google Calendar secret iCal address and a Home Assistant long-lived token
are **passwords**. Anyone with the ICS URL can read that calendar forever
without authenticating.
