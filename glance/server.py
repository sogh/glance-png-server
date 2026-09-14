"""HTTP layer. The device only ever needs GET /c/<channel>.png.

Everything else here exists for you, not the panel: a preview page for
designing at 192x32 on a normal monitor, and a status endpoint for working out
why a scene is not showing.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from . import artstore
from .fonts import FONTS
from .palette import NAMED
from .sprites import SPRITES
from .editor import editor_page
from .runtime import GlanceApp
from .scenes import REGISTRY
from .scenes.base import COMMON_PARAMS, schema_for, validate_params
from .scenes.static_image import list_static

log = logging.getLogger("glance")

# The device caches the image itself between refreshes, so any caching in
# front of us would only ever serve a stale frame and break the rotation.
NO_CACHE = "no-store, no-cache, must-revalidate, max-age=0"


def _coerce(value: str) -> Any:
    """Query strings are all text; scene params want real types."""
    low = value.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _brightness(request: Request) -> float | None:
    raw = request.query_params.get("brightness")
    if raw is None:
        return None
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return None


def _params(request: Request, drop: set[str]) -> dict[str, Any]:
    return {k: _coerce(v) for k, v in request.query_params.items() if k not in drop}


RESERVED_QUERY = {"peek", "k", "_", "width", "brightness"}

# Scenes that need an argument to show anything on the preview page. Without
# these, `text` renders its own "(no text)" placeholder, which
# tells you nothing about how they look.
PREVIEW_DEMO: dict[str, str] = {
    "text": "text=GOOD+MORNING&sub=IT+IS+A+FINE+DAY&color=amber",
    "countdown": "date=2026-12-25&label=XMAS",
    "sprite": "before=It%27s&after=season%21",
    "pulse": "items=ADA:yellow,GRACE:blue",
}

def _png_response(body: bytes, label: str, extra: dict[str, str] | None = None) -> Response:
    headers = {
        "Cache-Control": NO_CACHE,
        "Pragma": "no-cache",
        "X-Glance-Scene": label,
        "Content-Length": str(len(body)),
    }
    headers.update(extra or {})
    return Response(content=body, media_type="image/png", headers=headers)


class ChannelUpdate(BaseModel):
    entries: list[dict[str, Any]]


class CarouselUpdate(BaseModel):
    mode: str | None = None
    dwell: int | None = None
    min_advance_interval: float | None = None


def create_app(config_path: str | None = None) -> FastAPI:
    glance = GlanceApp.from_config(config_path or os.environ.get("GLANCE_CONFIG"))
    api = FastAPI(title="Glance PNG Server", version="1.0", docs_url="/api/docs")
    api.state.glance = glance
    token = glance.settings.access_token

    def require_token(request: Request) -> None:
        """Gate a route behind the shared secret, if one is configured.

        Only matters when the server is exposed beyond the LAN -- the Glance
        setup app refuses private addresses, so reaching it may mean putting
        it on the public internet, and the panel can carry calendar entries
        and todos.

        Answers 404 rather than 403 on a bad token: an unauthenticated caller
        should not be able to learn which channels exist.
        """
        if not token:
            return
        supplied = request.query_params.get("k") or request.headers.get("x-glance-token", "")
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=404, detail="not found")

    def resolve_options(marker: Any) -> Any:
        """Turn an "@..." marker into the live list it stands for."""
        if not isinstance(marker, str) or not marker.startswith("@"):
            return marker
        if marker == "@colors":
            return sorted(NAMED)
        if marker == "@fonts":
            return sorted(FONTS)
        if marker == "@sprites":
            return sorted(SPRITES)
        if marker == "@scenes":
            return sorted(REGISTRY)
        if marker == "@calendars":
            return glance.calendars.names
        if marker == "@languages":
            return glance.vocabulary.languages
        if marker == "@boards":
            return sorted(glance.scoreboards)
        if marker == "@entities":
            try:
                return glance.homeassistant.ids()[:400]
            except Exception:  # noqa: BLE001 - a dropdown must never break the page
                return []
        if marker == "@static":
            return [f.name for f in artstore.listing(glance.settings.static_dir)]
        return []

    def scene_catalogue() -> list[dict[str, Any]]:
        out = []
        for sid in sorted(REGISTRY):
            scene = REGISTRY[sid]
            params = [p.as_dict() for p in list(schema_for(sid)) + list(COMMON_PARAMS)]
            for entry in params:
                entry["options"] = resolve_options(entry["options"])
            out.append({
                "id": sid,
                "description": getattr(scene, "description", ""),
                "params": params,
            })
        return out

    def tokened(url: str) -> str:
        """Append the token to a URL the preview page will request."""
        if not token:
            return url
        return f"{url}{'&' if '?' in url else '?'}k={token}"

    @api.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/preview")

    @api.get("/healthz")
    def healthz() -> dict[str, Any]:
        # Stays open so uptime checks work, but says nothing about the
        # configuration when a token is in force.
        if token:
            return {"ok": True}
        return {"ok": True, "channels": sorted(glance.settings.channels)}

    @api.get("/api/status")
    def status(request: Request) -> JSONResponse:
        require_token(request)
        return JSONResponse(glance.status(), headers={"Cache-Control": NO_CACHE})

    @api.post("/api/reset")
    @api.post("/api/reset/{channel}")
    def reset(request: Request, channel: str | None = None) -> dict[str, Any]:
        """Put a channel's rotation back to its first available scene."""
        require_token(request)
        glance.carousel.reset(channel)
        return {"reset": channel or "all"}

    # --- editing the carousel ----------------------------------------------

    @api.get("/api/channels")
    def list_channels(request: Request) -> JSONResponse:
        require_token(request)
        overlay = glance.read_overlay()
        return JSONResponse({
            "channels": sorted(glance.settings.channels),
            "overridden": sorted(overlay.get("channels", {})),
            "scenes": sorted(s for s in REGISTRY if s != "static"),
            "static": [f"static:{n}" for n in list_static(glance.context())],
            "catalogue": scene_catalogue(),
            "carousel": {
                "mode": glance.settings.carousel_mode,
                "dwell": glance.settings.carousel_dwell,
                "min_advance_interval": glance.settings.carousel_min_advance,
            },
        }, headers={"Cache-Control": NO_CACHE})

    @api.get("/api/channels/{name}")
    def get_channel(name: str, request: Request) -> JSONResponse:
        require_token(request)
        if name not in glance.settings.channels:
            raise HTTPException(status_code=404, detail="no such channel")
        overlay = glance.read_overlay()
        return JSONResponse({
            "name": name,
            "entries": glance.channel_spec(name),
            "overridden": name in overlay.get("channels", {}),
        }, headers={"Cache-Control": NO_CACHE})

    @api.put("/api/channels/{name}")
    def put_channel(name: str, body: ChannelUpdate, request: Request) -> JSONResponse:
        require_token(request)
        # Validate before writing: a channel that cannot be parsed would take
        # the panel down until someone edited JSON by hand over SSH.
        from .config import _parse_entry

        warnings: list[str] = []
        for item in body.entries:
            try:
                parsed = _parse_entry(item)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"bad entry {item!r}: {exc}") from exc
            # A param that does not exist used to be accepted and then quietly
            # ignored, which is the worst of both. Report it without refusing
            # the save, since a config written before the schema may carry one.
            base = parsed.ref.split(":", 1)[0] if ":" in parsed.ref else parsed.ref
            warnings += [f"{parsed.ref}: {w}"
                         for w in validate_params(base, parsed.params, resolve_options)]

        glance.set_channel(name, body.entries)
        glance.carousel.reset(name)      # start the edited rotation from the top
        return JSONResponse({
            "saved": name,
            "entries": glance.channel_spec(name),
            "warnings": warnings,
        })

    @api.post("/api/channels/{name}/reset")
    def reset_channel(name: str, request: Request) -> JSONResponse:
        require_token(request)
        glance.reset_channel(name)
        glance.carousel.reset(name)
        return JSONResponse({"reset": name, "entries": glance.channel_spec(name)})

    @api.put("/api/carousel")
    def put_carousel(body: CarouselUpdate, request: Request) -> JSONResponse:
        require_token(request)
        values = {k: v for k, v in body.model_dump().items() if v is not None}
        if "mode" in values and values["mode"] not in ("advance", "clock"):
            raise HTTPException(status_code=400, detail="mode must be advance or clock")
        glance.set_carousel(values)
        return JSONResponse({"saved": values})

    # --- artwork -----------------------------------------------------------

    @api.get("/api/art")
    def list_art(request: Request) -> JSONResponse:
        require_token(request)
        files = artstore.listing(glance.settings.static_dir, glance.settings.width)
        return JSONResponse({
            "panel": {"width": glance.settings.width, "height": 32},
            "files": [f.__dict__ for f in files],
        }, headers={"Cache-Control": NO_CACHE})

    @api.post("/api/art")
    async def upload_art(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        require_token(request)
        data = await file.read()
        try:
            saved = artstore.save(
                glance.settings.static_dir, file.filename or "", data,
                glance.settings.width,
            )
        except artstore.ArtError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"saved": saved.__dict__})

    @api.delete("/api/art/{name}")
    def delete_art(name: str, request: Request) -> JSONResponse:
        require_token(request)
        if not artstore.delete(glance.settings.static_dir, name):
            raise HTTPException(status_code=404, detail="no such file")
        return JSONResponse({"deleted": name})

    @api.get("/edit", response_class=HTMLResponse)
    def edit(request: Request) -> HTMLResponse:
        require_token(request)
        return HTMLResponse(editor_page(token), headers={"Cache-Control": NO_CACHE})

    # --- the endpoint the Glance actually points at ------------------------

    @api.get("/c/{channel}")
    def channel_png(channel: str, request: Request) -> Response:
        require_token(request)
        name = channel[:-4] if channel.endswith(".png") else channel
        # ?peek=1 renders without consuming a rotation slot -- used by the
        # preview page so opening it in a browser does not skip scenes.
        peek = request.query_params.get("peek") in ("1", "true", "yes")
        width = request.query_params.get("width")
        canvas, selection, label = glance.render_channel(
            name, advance=not peek, width=int(width) if width else None,
            brightness=_brightness(request),
        )
        extra = {"X-Glance-Channel": name}
        if selection is not None:
            extra["X-Glance-Position"] = f"{selection.position + 1}/{selection.total}"
            if selection.takeover:
                extra["X-Glance-Takeover"] = "1"
        return _png_response(glance.png(canvas), label, extra)

    @api.get("/s/{ref}")
    def scene_png(ref: str, request: Request) -> Response:
        require_token(request)
        name = ref[:-4] if ref.endswith(".png") else ref
        width = request.query_params.get("width")
        canvas, label = glance.render_scene(
            name, _params(request, RESERVED_QUERY), width=int(width) if width else None,
            brightness=_brightness(request),
        )
        return _png_response(glance.png(canvas), label)

    # --- preview ------------------------------------------------------------

    @api.get("/preview", response_class=HTMLResponse)
    def preview(request: Request) -> HTMLResponse:
        require_token(request)
        ctx = glance.context()
        zoom = int(request.query_params.get("zoom", 4))
        # Design at full brightness unless asked otherwise: judging artwork
        # through the evening dimming curve is misleading.
        live = request.query_params.get("live") in ("1", "true", "yes")
        bright_q = "" if live else "&brightness=1"
        info = glance.status()

        def frame(src: str, title: str, note: str = "") -> str:
            if bright_q:
                src += ("&" if "?" in src else "?") + "brightness=1"
            src = tokened(src)
            return (
                f'<figure><img src="{src}" alt="{title}" '
                f'style="width:{glance.settings.width * zoom}px">'
                f"<figcaption><b>{title}</b>"
                + (f"<span>{note}</span>" if note else "")
                + "</figcaption></figure>"
            )

        parts: list[str] = []
        for name, meta in info["channels"].items():
            avail = ", ".join(meta["available"]) or "nothing available"
            # The current frame, and then every entry in the rotation. Showing
            # only the current one made a channel look like it held a single
            # scene: a two-board `scores` channel rendered whichever board was
            # up and the other was nowhere on the page.
            shots = [frame(f"/c/{name}.png?peek=1", f"{name} (current)")]
            for entry in glance.settings.channels.get(name, []):
                if not entry.enabled:
                    continue
                note = " ".join(
                    filter(None, ("takeover" if entry.takeover else "",
                                  f"when {entry.when}" if entry.when else ""))
                )
                shots.append(frame(f"/s/{entry.ref}.png?{urlencode(entry.params)}",
                                   entry.key, note))
            parts.append(
                f"<h2>channel <code>{name}</code></h2>"
                f'<p class="meta">/c/{name}.png &middot; {len(meta["available"])} '
                f"of {meta['configured']} showing &middot; {avail}</p>"
                f'<div class="grid">{"".join(shots)}</div>'
            )

        def scene_url(sid: str) -> str:
            demo = PREVIEW_DEMO.get(sid)
            return f"/s/{sid}.png?{demo}" if demo else f"/s/{sid}.png"

        scene_frames = "".join(
            frame(scene_url(sid), sid, REGISTRY[sid].description
                  if hasattr(REGISTRY[sid], "description") else "")
            for sid in sorted(REGISTRY) if sid != "static"
        )
        static_frames = "".join(
            frame(f"/s/static:{n}.png", f"static:{n}") for n in list_static(ctx)
        )

        html = f"""<!doctype html><meta charset="utf-8">
<title>Glance preview</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ background:#101014; color:#c8c8d0; font:13px ui-monospace,SFMono-Regular,Menlo,monospace;
        margin:0; padding:24px 28px 60px; }}
 h1 {{ font-size:15px; letter-spacing:.14em; text-transform:uppercase; color:#fff; margin:0 0 4px; }}
 h2 {{ font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:#7f8; margin:32px 0 2px; }}
 h3 {{ font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:#89f; margin:36px 0 8px;
       border-top:1px solid #26262e; padding-top:16px; }}
 p.meta {{ color:#6a6a78; margin:0 0 10px; }}
 code {{ color:#fd8; }}
 figure {{ margin:0 0 18px; }}
 img {{ image-rendering:pixelated; display:block; background:#000;
        border:1px solid #2a2a34; border-radius:2px; max-width:100%; }}
 figcaption {{ display:flex; gap:12px; padding-top:5px; color:#8a8a98; }}
 figcaption span {{ color:#5a5a68; }}
 .grid {{ display:flex; flex-wrap:wrap; gap:20px; }}
 a {{ color:#7cf; }}
</style>
<h1>Glance preview &mdash; {glance.settings.width}&times;32 at {zoom}&times;</h1>
<p class="meta">{info['now']} &middot; carousel <code>{info['carousel']['mode']}</code>
 &middot; <a href="{tokened('/edit')}">edit carousel</a>
 &middot; <a href="{tokened('/preview?live=1' if not live else '/preview')}">{'showing full brightness' if not live else f'showing live level {info["panel"]["brightness"]}'}</a>
 &middot; <a href="{tokened('/api/status')}">status json</a>
 &middot; <a href="{tokened(f'/preview?zoom={3 if zoom != 3 else 5}')}">toggle zoom</a></p>
{"".join(parts) or "<p class='meta'>No channels configured.</p>"}
<h3>All scenes</h3><div class="grid">{scene_frames}</div>
<h3>Static artwork ({len(list_static(ctx))})</h3><div class="grid">{static_frames
    or "<p class='meta'>Drop PNGs into assets/static/ to see them here.</p>"}</div>
<script>
 // Reload just the images so the page does not jump while you iterate on art.
 setInterval(() => document.querySelectorAll('img').forEach(i => {{
   const u = new URL(i.src, location.href);
   u.searchParams.set('_', Date.now());
   i.src = u.pathname + u.search;
 }}), 10000);
</script>"""
        return HTMLResponse(html, headers={"Cache-Control": NO_CACHE})

    return api


app = create_app()
