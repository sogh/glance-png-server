# What the Glance Scroll actually does

Facts about the device and the Glance platform, gathered while building this.
Each is marked **[docs]** if it comes from
[glance-led.dev](https://glance-led.dev/docs/private-apps/) or **[tested]** if
it was established here by experiment — several of the important ones are not
documented anywhere, and two contradict the documentation.

---

## The panel

| | |
|---|---|
| Height | **always 32px** — there is no other option **[docs]** |
| Width | 1–384px, built from **64px modules** chained together **[docs]** |
| This one | 192×32, three modules, confirmed against the hardware **[tested]** |
| Colour | full RGB; name, `#hex` or `(r,g,b)` **[docs]** |

Chained modules show **one continuous image**, not three screens. That is why
the `columns` scene divides 192 into three 64px columns — the layout lands on
the hardware's own seams.

A **panel** (a physical module) and a **private app slot** (a page of content)
are different things and easy to confuse. The device cycles between slots on
its own clock, every few seconds. Up to 10 slots. **[docs]**

## Images

| | |
|---|---|
| Format | **PNG only**. JPEG is not decoded **[docs]** |
| Animation | **APNG does not animate** — frame 0 is drawn, then it stops **[tested]** |
| Response cap | 1 MB **[docs]** — ours run 150–600 bytes |
| Request timeout | ~4 seconds **[docs]** |

**APNG was tested on the hardware and does not work.** This is not documented
either way. It is a defensible engineering call — multi-frame buffering is
real memory on a chip driving LED matrices — but it means motion has to come
from somewhere else. What still moves: the device cycling between slots.

Because an APNG is a valid PNG, sending one would be harmless -- the panel
would show frame zero -- but paying for thirty frames nobody sees is
pointless, so this server does not emit them at all. The `pulse` scene, which
began as an animation, now runs its colour transition across the letters
instead of across time.

## Fetching

| | |
|---|---|
| Who fetches | **the device itself, over your own network** **[docs]** |
| Protocol | **plain HTTP. Not HTTPS** — a deliberate design choice **[docs]** |
| Method | GET only **[docs]** |
| Refresh | 60s practical minimum, 300s default **[docs]** |
| Caching | the device caches and redraws between fetches **[docs]** |

Glance's servers store only the URL string. The image is never uploaded to,
stored on, or proxied through them. **So a LAN address works and no tunnel is
needed** — as long as the device and server share a network.

The HTTP-only constraint rules out the obvious reflex of `cloudflared tunnel`,
which hands back an `https://` hostname and redirects HTTP to HTTPS. An
HTTP-only client cannot follow that.

## Adding a private app: the URL is checked

Adding a private app runs a verification step the developer docs do not
mention. It resolves your hostname and inspects the address, and it refuses
private and reserved ranges: **[tested]**

```
Image verification failed. host resolves to a private/reserved IP - refused
```

That is ordinary SSRF protection and correct on their side — a service that
fetches user-supplied URLs can otherwise be aimed at cloud metadata endpoints.
It does sit awkwardly against the documentation's claim that *"a Raspberry Pi
on your own network works too."*

The part worth knowing is that **verification happens only when you add the
app**. Every fetch afterwards is the device asking your server directly, over
whatever network they share. **[tested]**

So the server needs to be reachable from outside at the moment you add it, and
after that it does not. [docs/DEPLOY.md](DEPLOY.md) covers the practical
options.

## Keep one stock app installed

A rotation containing **only private apps** reboots the device roughly every
150 seconds — about 25 times an hour. Installing any single stock app stops it
completely. **[tested]**

| | private apps only | + one stock app |
|---|---|---|
| Reboots | ~25/hr, steady across every window sampled | **0** |
| Longest clean run | none | 50 min, where ~21 were expected |

This is worth stating plainly because **every symptom points at your server**.
The device boots, refetches every slot at once, runs for two minutes and
reboots — so what you see in your access log is a burst of requests for all
your channels every couple of minutes, forever. The natural suspects are image
size, PNG format, too many slots, a slow response. All of them are wrong, and
all of them are things you can spend a day tuning without effect.

None of it mattered here: the payloads were 150–600 byte palette PNGs, every
one of 4,597 requests returned `200 OK`, and the same six private apps had run
for a full day without a single reboot while one stock app was still
installed. The only thing that changed was the last stock app being removed.

The likely mechanism is that private apps are fetched **straight from your own
network**, so an all-private rotation is the one configuration in which the
device never has any reason to contact Glance's servers at all. That path
appears not to be handled.

The fix costs one slot and about twelve seconds of screen time per cycle: keep
a stock app you don't mind parked in the rotation.

### Telling a reboot from a quiet device

The device's **source port** is the signal, and your access log already has
it. A healthy device holds one monotonically increasing ephemeral-port
sequence for days — through idle stretches and overnight sleeps. A reboot
re-randomises the base, so every restart appears as a discontinuity:

```
17:49:27  main    port 54206     healthy: 54008 -> 54206 unbroken, 20 minutes
17:50:01  main    port 56988     rebooted - base re-randomised
17:50:01  date    port 56989     every slot refetched inside one second
```

Count the jumps larger than a couple of hundred and you have reboots per hour.

**Do not use ping for this.** These panels run aggressive WiFi power saving:
ICMP latency runs ~100x the LAN norm, with frequent multi-second gaps, even
when the device is perfectly healthy and serving every request. A ping log
will convince you the network is broken when it is not. **[tested]**

## Community apps (and why their clock is wrong)

Apps published to the catalogue are **Starlark** (`app.star` + `manifest.yaml`)
and execute **on Glance's servers**, not the device: *"On Glance's servers a
render also runs under a CPU cap (~25 CPU-seconds)"*. The only network access
is `http.get`, which the host performs. **[docs]**

That explains a symptom you may have noticed: Glance's own clock app running
hours behind. Server-side rendering with a 300s TTL cache keyed on
`(url, params, headers)` does that to a clock. It is also why a community app
cannot reach your LAN at all — the topology forbids it, not a filter.

## Practical limits this imposes

- **No real animation.** Gradients across letters, not across time.
- **No clock you can trust.** The device redraws a cached image for up to a
  full refresh interval, so a clock is wrong most of the time it is on screen.
  Prefer a date. The `clock` scene takes a `lead` to centre the error.
- **Pace is yours to control, not the device's.** It decides when to fetch;
  the only lever is returning the same thing until you want it to change.
  That is what per-entry `dwell` is for.
- **Keep one stock app.** An all-private rotation reboots the device every
  ~150s. Costs a slot; saves a weekend of blaming your own PNGs.
- **Design for glanceability.** *"A photo shrunk to 32 pixels turns to mush; a
  chunky icon and large text look great."* **[docs]**
