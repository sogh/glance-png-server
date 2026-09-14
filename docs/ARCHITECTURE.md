# How this is put together

A map of the code, and the reasoning behind the decisions that are not
obvious from reading it.

---

## Shape

```
device ──GET /c/<channel>.png──▶ server
                                   │
                          carousel picks a scene
                                   │
                     scene renders onto a Canvas
                                   │
                   brightness applied for the hour
                                   │
                              PNG bytes
```

| Module | Does |
|---|---|
| `canvas.py` | The drawing surface. Rects, discs, text, gradients, PNG encoding. |
| `fonts.py` | Three hand-authored bitmap fonts and their layout. |
| `palette.py` | LED-safe colours, PWM floor snapping, mixing. |
| `sprites.py` | Pixel art as editable character grids. |
| `weathericons.py` | Weather glyphs drawn from primitives. |
| `brightness.py` | Time-of-day dimming curve. |
| `animation.py` | Multi-frame output as APNG. |
| `carousel.py` | Which scene this fetch gets. |
| `config.py` | `settings.yaml` + the editor's overlay. |
| `runtime.py` | Composition root. Owns sources, applies dimming, hot-reloads. |
| `server.py` | FastAPI routes, preview page. |
| `editor.py` | The `/edit` page. |
| `artstore.py` | Uploading and validating artwork. |
| `scenes/` | One module per scene. A render function plus a param schema. |
| `sources/` | Calendars, reminders, holidays, weather, baseball, Instagram, modes, scoreboards. |

## Decisions worth knowing

**Scoreboards share one vocabulary.** Every provider speaks its own dialect --
MLB says `abstractGameState`, ESPN says `STATUS_FINAL`, the WPBL's WordPress
says `final`. Each source translates into `sources/scores.py::Fixture` and a
single `scores` scene draws all of them, so a new league is a config entry.
MLB keeps its bespoke source and scene because statsapi carries the current
half-inning and per-side broadcast feeds that the neutral shape has no room
for.

The followed team is stored **on each fixture**, not once on the snapshot.
Follow two teams and the last result and the next fixture routinely belong to
different ones; a single team would then be wrong for at least one of them and
"did we win" would answer None for a game plainly won.

**ESPN wants no User-Agent.** Its edge 403s a browser-shaped UA and an
unrecognised custom one, but serves `python-httpx/...` and `curl/...`. The
source therefore sets no header. Adding a realistic browser UA is the obvious
"fix" that breaks it.

**Modes are calendar-driven, not a button.** A toggle needs two presses and
the second one — days later, once the visitors have gone — is the one that
gets forgotten. An event carries its own end time, so the panel un-does
itself. `sources/modes.py` decides which modes are in force; `when: {mode: x}`
on a channel entry consumes it.

Working it out costs a calendar parse, so `RenderContext.modes` is lazy and
memoised for the life of one request, and `Carousel.candidates` only asks when
an entry's `when` actually mentions a mode. A feature most panels never touch
should not tax every render.

Mode detection deliberately sees `#hide` events, which every other reader
skips. Hiding the trigger event from the agenda is a reasonable thing to want,
and it would be baffling if that also silently disarmed the mode.

**Bitmap fonts, hand-authored.** At 32px tall, anti-aliased TrueType turns to
grey mush — every glyph edge becomes a half-lit LED. The glyphs are editable
pixel art in `fonts.py`: `#` lit, `.` dark, rows separated by `/`. Three
missing-glyph bugs reached the panel during development (`%` drew as `13?`,
`@` as `?handle`, `&` as `Health ? Wealth`) because a missing glyph
falls back silently. There is now a test asserting both fonts cover the
characters the scenes actually draw.

**Sprites are typed, weather icons are drawn.** Sweatpants are easier to author
character by character than to describe; circles and clouds are the reverse.
The two approaches sit side by side deliberately.

**The editor never writes to `settings.yaml`.** It writes `data/overrides.json`,
which is layered over the parsed config. That file is hand-authored with
comments explaining reasoning; round-tripping it through a web form destroys
them and guarantees conflicts with the repo. It also makes "reset to file" a
key deletion, and means a deploy cannot clobber UI edits. A channel in the
overlay *replaces* that channel wholesale rather than merging by index.

**Scenes declare their parameters.** Name, type, default, bounds, options.
The editor draws real controls from that, and a save reports anything it does
not recognise. Before this the params were a raw JSON box and a typo was
silently ignored. Options are markers (`@sprites`, `@calendars`) resolved
against live state, so the lists are never stale.

**Stale beats blank, and blank beats wrong.** Every source serves its cached
copy when a fetch fails. A broken scene renders an error card at HTTP 200, not
a 500 — the device caches its last successful fetch, so a 5xx is invisible and
looks exactly like a working panel. Where a stale number could mislead
(Instagram), its age is drawn on the panel; where no honest value exists, the
scene says so rather than drawing a zero.

**Brightness is applied once, at the end.** To the finished canvas, including
artwork loaded from a file, so no scene has to think about it. A lit pixel
never rounds to black — that would punch holes in artwork — and a channel that
was zero stays zero, so dimming cannot tint a pure colour.

**Pace is controlled by holding, not by timing.** The device decides when to
fetch. The only lever is returning the same scene until its `dwell` expires.

**Two layers of cycling compose.** The device flips between slots every few
seconds; a channel rotates its own contents on every refresh. Pointing several
slots at different channels gives both.

**Continuity is measured in columns, not days.** `columns` panels pair with
`skip_columns`, because whether the near panel spilled is exactly what decides
where the far one should start. A day offset cannot know that.

## A note on testing pictures

`Canvas.to_ascii()` thresholds every pixel to lit or unlit. That is exactly
right for a sparse text scene and blind for a full-bleed one: two completely
different skies both come out as solid blocks of `#`, and a test comparing
them passes while seeing nothing. The same trap catches pixel *counts* —
drawing dark text on a coloured sky changes values without changing how many
pixels are lit.

Scenes that fill the canvas are compared by
`list(canvas.image.get_flattened_data())`, or by sampling the specific region
under test. Both mistakes were made here and both were caught by a test that
failed for the right reason.

## Testing

`.venv/bin/python -m pytest -q` — 412 tests, ~5s, no network.

Every external source is exercised through a primed disk cache or a local
HTTP server rather than the live API, so the suite is offline and
deterministic. The parts most worth the coverage are the ones that fail
silently: font glyph coverage, date maths across year boundaries, ICS
recurrence and timezone conversion, carousel rotation and takeover semantics,
deploy exclusions, and that every endpoint returns a valid 192×32 PNG even
when a scene throws.

## Deployment

`deploy/pve-deploy.sh` runs from a laptop, over one SSH hop to a Proxmox host,
and drives the container with `pct` — the container never needs sshd. It is
idempotent: the same command creates and updates, which makes it the artwork
loop too.

`data/` never travels: rotation state, caches, the editor overlay and `.env`
are all excluded. That was a bug once — the overlay was shipping and silently
discarding every channel edit — and there are now tests asserting the
exclusions exist.
