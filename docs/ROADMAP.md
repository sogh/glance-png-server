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

Partly done. The reference material now lives in `docs/CONFIG.md`,
`docs/SCENES.md` and `docs/API.md`, which is most of the bulk. What remains:
the README is still an operations manual with **one household's IP addresses
and hostnames throughout** — `192.168.1.50`, `glance.example.com`, a UniFi
gateway. A stranger needs those replaced with placeholders and the LAN/DNS
material moved into a deployment guide. That is the last thing standing
between this and being publishable.

---

## Documentation

Done: a generated scene and parameter reference (`tools/gendocs.py` →
`docs/SCENES.md`, with a test that fails when it drifts), a configuration
reference covering every key and environment variable, and an HTTP reference
covering every route. Every scene parameter now carries help text, which the
editor shows and the generator picks up.

Still thin:

- **No screenshots anywhere.** A panel server whose docs contain no pictures
  of panels is a strange artefact. The preview page renders them all already;
  the missing piece is committing a few PNGs and referencing them.
- **No CONTRIBUTING or scene-authoring walkthrough.** "Adding a scene" in the
  README is a code sketch, not a guide.
- **Personal data in the tracked tree.** `data/reminders.json` and
  `data/overrides.json` are versioned but excluded from deploys, so the repo
  copy is both stale and the wrong shape for a stranger. They want
  gitignoring, with an `.example` shipped instead — as `.env` already does.

## Open items, unrelated to packaging

- **`reminders` calendar not created.** `GLANCE_ICS_REMINDERS` is unset, so
  that channel shows its empty state. The channel currently serves weather
  instead.
- **Instagram is untested against the live API.** The code handles both
  response shapes and every failure path, but it has never made a real call —
  that needs a Meta app and token.
- **The UDM Pro's admin UI answers on the public internet.** Nothing to do
  with this project; found while diagnosing the port forward. Worth closing.

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
