# Contributing

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # then fill in what you use
.venv/bin/python -m glance      # http://localhost:8080/preview
```

`/preview` renders every channel, every entry, every scene and every piece of
static art, and reloads the images without reloading the page. Keep it open.

```bash
.venv/bin/python -m pytest -q             # the whole suite, ~5s, no network
.venv/bin/python tools/render.py sky      # one scene, as ASCII in the terminal
.venv/bin/python tools/render.py sky --png /tmp/sky.png --scale 6
.venv/bin/python tools/gendocs.py         # regenerate docs/SCENES.md
.venv/bin/python tools/screenshots.py     # regenerate the README gallery
```

## Adding a scene

A scene is a function that draws on a `Canvas` and a declaration of the knobs
it takes. Put it in `glance/scenes/`, add it to the import list in
`glance/scenes/__init__.py`, and run `tools/gendocs.py`.

```python
@register("greeting", description="Says hello",
          params=[Param("name", "text", "world", help="Who to greet")])
def render_greeting(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear("black")
    c.centered(f"hello {params.get('name', 'world')}", "white", "5x7")
    return c
```

Declare every parameter with `help` text. It draws the control in `/edit`,
validates a save, and fills `docs/SCENES.md` — a parameter without it is
undocumented in three places at once, and a test will fail.

Scenes never fetch. Everything comes from `ctx`, so a scene is a pure function
of its inputs and can be tested without a network.

## What this codebase cares about

**The device is the constraint.** 192×32, PNG only, plain HTTP, ~4s to answer,
no animation. See [docs/DEVICE.md](docs/DEVICE.md) — most of the surprising
decisions here are downstream of something in that file.

**Centre content as one group, inside a margin.** `layout.py` has the rule and
the helpers; use them rather than working out `(width - content) // 2` again.
The margin is a floor, not an inset, and decoration follows the content rather
than the panel edge. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Never block a render.** The device gives up after about four seconds and
caches whatever it last got, so a slow fetch shows a stale panel with no
indication anything is wrong. Sources cache to disk and serve stale data
rather than nothing; logos are fetched on a background thread.

**Fail where it can be seen.** A broken source draws a card saying so. A
scene that raises draws a red error card rather than a 500, because a 500 and
a working panel look identical on a device that caches.

**Say what is not known.** A score that has not been entered is drawn as
absent, not as nil. A count that could not be refreshed says how old it is.

**Comments explain why, not what.** The interesting lines here are the ones
that look wrong until you know what they are avoiding — why ESPN gets no
User-Agent, why the moon's terminator is settled by illumination at the
extremes, why the WPBL cache key includes the field list.

## Tests

No network, no clock dependence, no real credentials. Seed a cache file or
fake a source; several test modules refuse network access outright so that a
fixture written to the wrong path fails instead of quietly reaching the
internet.

Testing pictures is its own problem — `to_ascii()` thresholds to binary, so
two visibly different panels can compare equal. Compare
`image.get_flattened_data()` or sample regions. See the note in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Style

Plain Python, no framework beyond FastAPI and Pillow, dependencies added
reluctantly. Line length 88ish. Prose in comments and docs, not telegrams.
