# HTTP reference

Every route the server serves. There are only three you point hardware at —
`/c/<channel>.png`, `/preview` and `/edit` — and the rest exist so the editor
and a shell can do their jobs.

**Token.** If `server.access_token` is set, every route below except
`/healthz` requires `?k=<token>` or an `X-Glance-Token` header. A wrong or
missing token answers **404, not 403**, so a stranger cannot learn that a
channel exists by being refused.

---

## Images

### `GET /c/{channel}.png`

**The one the device fetches.** Returns the next scene in that channel's
rotation, as a PNG.

| Query | Means |
|---|---|
| `peek=1` | Render without consuming a rotation slot. The preview page uses this so opening it in a browser does not make the device skip scenes. |
| `width=N` | Render at another width, to check what your hardware actually is. |
| `brightness=0..1` | Override the time-of-day dimming. |

Response headers say what you got, which is the quickest way to debug a
channel without opening an image:

```
X-Glance-Channel: scores
X-Glance-Scene:   scores(accent=sky,board=mariners)
X-Glance-Position: 3/4
X-Glance-Takeover: 1        (only when a takeover entry pre-empted the rotation)
Cache-Control: no-store, no-cache, must-revalidate, max-age=0
```

The no-cache headers matter: the device caches aggressively and will happily
redraw a stale image for a full refresh interval otherwise.

### `GET /s/{ref}.png`

Render one scene directly, ignoring channels. Query parameters become scene
parameters, so this is how you try something before committing it to config:

```
/s/banner.png?title=EVERGREEN+FARM&subtitle=WELCOME&accent=mint
/s/scores.png?board=mariners&crest=16
/s/static:winter.png
```

`width` and `brightness` work as above. Anything else is passed to the scene.

A failure is **drawn, not raised** — a red error card with the reason on it.
The device caches the last image it fetched, so a 500 would look exactly like
a working panel; a card that says `unknown scene langauge` does not.

---

## Pages

### `GET /preview`

Every channel, every entry in every channel, every scene, and every piece of
static artwork, rendered at `zoom`× and auto-refreshing. The fastest way to
see what a change did.

| Query | Means |
|---|---|
| `zoom=N` | Pixel scale, default 4. |
| `live=1` | Show the real dimming level instead of full brightness. |

### `GET /edit`

Edit channels and carousel settings in a browser. Writes to
`data/overrides.json`, never to `settings.yaml` — see [CONFIG.md](CONFIG.md).
Also uploads artwork.

### `GET /`

Redirects to `/preview`.

---

## Status

### `GET /healthz`

Unauthenticated liveness check. Returns the channel names, which makes it a
useful one-line "is it up and what does it have":

```json
{"ok": true, "channels": ["date", "learn", "main", "next", "reminders", "scores", "today"]}
```

### `GET /api/status`

Everything the server knows about itself: the current time, panel size and
brightness, carousel settings, every channel with which entries are currently
available, the scene registry, static art, holidays, active modes, and the
health of every source.

```bash
curl -s localhost:8080/api/status | jq .modes
curl -s localhost:8080/api/status | jq '.channels.scores'
curl -s localhost:8080/api/status | jq '.sources | keys'
```

Source entries carry `last_error`, which is where a silently-empty panel
explains itself.

---

## Channels

### `GET /api/channels`

Every channel and its entries, in the shape `PUT` expects.

### `GET /api/channels/{name}`

One channel. Also returns the scene catalogue and parameter schemas, which is
what draws the controls in `/edit`.

### `PUT /api/channels/{name}`

Replace a channel's entries. Body is the full list — the editor always sends
all of it, because merging arrays by index is a reliable source of surprises.

```bash
curl -X PUT localhost:8080/api/channels/main \
  -H 'content-type: application/json' \
  -d '{"entries": [{"ref": "date"}, {"ref": "weather"}]}'
```

Writes to the overlay. `settings.yaml` is never touched.

### `POST /api/channels/{name}/reset`

Delete the overlay entry for this channel, reverting it to whatever
`settings.yaml` says.

### `PUT /api/carousel`

Set `mode`, `dwell` or `min_advance_interval`.

### `POST /api/reset`, `POST /api/reset/{channel}`

Reset carousel *rotation position* — where in the list each channel had got
to. Not the same as `/api/channels/{name}/reset`, which resets configuration.

---

## Artwork

### `GET /api/art`

List the PNGs in `static_dir`.

### `POST /api/art`

Upload one, multipart. Filenames are sanitised hard: path traversal is
flattened, shell metacharacters are refused, only image extensions are
accepted, and the content is decoded to confirm it really is an image before
anything is written.

### `DELETE /api/art/{name}`

Remove one.

---

## Interactive docs

FastAPI serves its own schema at `/api/docs`.
