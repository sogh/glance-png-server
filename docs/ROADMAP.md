# Where this goes next

## Packaging for other people

Decided: **MIT licensed, aimed at self-hosting on a private LAN.** Anyone who
wants to put it on the public internet may, but that is not the case being
designed for.

The audit that matters: ~9,900 lines across 53 modules, 6,000 lines of tests,
**9** pinned dependencies, no native extensions, and almost nothing
hard-coded. Everything personal lives in `config/settings.yaml` and `.env`.
That is already a portable shape.

### Three walls a stranger hits, in order

**1. The setup app refuses LAN addresses.** Everybody meets this, it is
undocumented, and it stops them before they see a single panel. Whatever the
packaging, this has to be answered on the first page — currently the knowledge
is buried in a troubleshooting section. See `docs/DEVICE.md`.

**2. First run means editing YAML over SSH.** `/edit` covers channels now, but
timezone, panel width and calendar URLs are still hand-edited.

**3. Deployment is Proxmox-only.** Fine here, useless to somebody with a Pi or
a Synology.

### The ladder, in the order worth building

**Docker image + compose file.** The foundation everything else stands on.
`docker run -v ./config:/config -p 8080:8080` covers Pi, Synology, Unraid,
Umbrel, CasaOS. The Proxmox script then collapses to "make an LXC, run the
container", which is shorter than what exists.

**A first-run setup wizard.** The largest usability jump available: on first
launch, with no config present, serve a form instead of a panel — timezone,
width, optional calendar URLs, coordinates — and write the YAML from it. Turns
"clone, edit, deploy" into "run, open browser".

**A Home Assistant add-on.** Add-ons are Docker images plus a manifest, the
audience overlaps almost exactly with people who own one of these, and HA's
ingress gives the editor an authenticated URL for free.

**App-store manifests** — Umbrel, CasaOS, Unraid CA. All take the Docker image
and a small YAML file.

### README split

**Done.** The reference material now lives in `docs/CONFIG.md`,
`docs/SCENES.md` and `docs/API.md`, which is most of the bulk. Addresses and hostnames are placeholders now
(`192.168.1.50`, `glance.example.com`), the personal defaults are generic, and
`data/overrides.json` and `data/reminders.json` are untracked with `.example`
files shipped in their place.

---

## Documentation

Done: a generated scene and parameter reference (`tools/gendocs.py` →
`docs/SCENES.md`, with a test that fails when it drifts), a configuration
reference covering every key and environment variable, and an HTTP reference
covering every route. Every scene parameter now carries help text, which the
editor shows and the generator picks up.

Also done: a screenshot gallery (`tools/screenshots.py`, rendered from
invented data so it leaks nobody's Tuesday and ships no third-party team
marks), a CONTRIBUTING guide, and a `.env.example` that matches what
`settings.yaml` actually references.

Still thin:

- **No per-scene screenshots in SCENES.md.** The generator writes one file per
  panel; wiring them into the generated reference is a small step.
- **No walkthrough of a real first run** end to end, with a photograph of the
  hardware showing it.

## Known gaps

- **The Docker image has never been built.** The `Dockerfile` and compose file
  were written on a machine with no Docker. The *layout* they describe is
  tested — the server was run against the same `/config` + `/data` split and
  served every route — but the build itself is unverified. First thing to
  confirm.
- **Instagram is untested against the live API.** The code handles both
  response shapes and every failure path, but it has never made a real call —
  that needs a Meta app and token.
- **Only tested on Python 3.13 and 3.14.** The floor is declared 3.10 because
  that is what the dependencies require; nothing between has been run.
- **No CI.** The suite is fast, offline and deterministic, so a GitHub Actions
  workflow running `pytest` across 3.10–3.13 is a small and obvious win.

## Ideas considered and parked

- **Home Assistant sensors as a source.** Wanted, deferred until the entities
  settle. HA is at a known address on the LAN.
- **Cross-channel deduplication.** Channels are independent, so `today` and
  `next` can both surface the same meeting. The server knows what every
  channel is about to serve and could avoid the collision.
- **Frame history.** A ring buffer of recent PNGs, to answer "what was it
  showing at 3pm?".
- **Stale-source alerting.** If a calendar has been failing for hours, say so
  on the panel rather than quietly serving old events.
- **Multi-device.** Two panels of different widths, each with its own channels.
