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

Because an APNG is a valid PNG, sending one is harmless; the panel shows frame
zero. The animated scenes here default to a single frame anyway, since paying
for thirty frames nobody sees is pointless. `mode: pulse` still emits APNG if
a future firmware ever changes this.

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

## The setup app's URL check — the one that will catch you out

Adding a private app runs a verification step **the developer docs do not
mention at all**. It rejects addresses on your own network: **[tested]**

```
Image verification failed. host resolves to a private/reserved IP - refused
```

It resolves the hostname and then inspects the address, refusing private and
reserved ranges. That is ordinary SSRF protection and correct on their side —
a server that fetches user-supplied URLs can otherwise be aimed at cloud
metadata endpoints. It simply contradicts the documentation's claim that *"a
Raspberry Pi on your own network works too."*

Consequences worth knowing:

- A bare LAN IP is refused.
- **A wildcard-DNS alias does not help.** `192.168.1.50.nip.io` resolves
  publicly, but the verifier checks the resolved *address*, not the name.
- **Verification happens only when you add the app.** Confirmed by experiment:
  point the app at a temporarily-reachable URL, add it, then close the
  forward — the device keeps fetching over the LAN indefinitely. **[tested]**

The working shape is split-horizon DNS: a name that resolves publicly to
something non-private, and locally to the server. See the deployment guide.

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
- **Design for glanceability.** *"A photo shrunk to 32 pixels turns to mush; a
  chunky icon and large text look great."* **[docs]**
