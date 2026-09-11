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

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .editor import editor_page
from .runtime import GlanceApp
from .scenes import REGISTRY
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


def _params(request: Request, drop: set[str]) -> dict[str, Any]:
    return {k: _coerce(v) for k, v in request.query_params.items() if k not in drop}


RESERVED_QUERY = {"peek", "k", "_", "width"}

# Scenes that need an argument to show anything on the preview page. Without
# these, `text` and `marquee` render their own "(no text)" placeholder, which
# tells you nothing about how they look.
PREVIEW_DEMO: dict[str, str] = {
    "text": "text=GOOD+MORNING&sub=IT+IS+A+FINE+DAY&color=amber",
    "marquee": "text=SCROLLING+MARQUEE+TEXT&color=amber",
    "countdown": "date=2026-12-25&label=XMAS",
    "sprite": "before=It%27s&after=season%21",
    "pulse": "items=ADA:yellow,GRACE:blue",
}

# Marquees shown in the animation strip, as (label, query).
PREVIEW_ANIMATIONS: list[tuple[str, str]] = [
    ("marquee, 5x7", "text=MERRY+CHRISTMAS+FROM+THE+HOUSE&color=green"),
    ("marquee, double height", "text=SHIP+IT&color=amber&scale=2"),
    ("marquee, slow + small", "text=a+quiet+scrolling+line+of+text&font=3x5&step=1&duration=120"),
]


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

        for item in body.entries:
            try:
                _parse_entry(item)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"bad entry {item!r}: {exc}") from exc

        glance.set_channel(name, body.entries)
        glance.carousel.reset(name)      # start the edited rotation from the top
        return JSONResponse({"saved": name, "entries": glance.channel_spec(name)})

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
            name, advance=not peek, width=int(width) if width else None
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
            name, _params(request, RESERVED_QUERY), width=int(width) if width else None
        )
        return _png_response(glance.png(canvas), label)

    # --- preview ------------------------------------------------------------

    @api.get("/preview", response_class=HTMLResponse)
    def preview(request: Request) -> HTMLResponse:
        require_token(request)
        ctx = glance.context()
        zoom = int(request.query_params.get("zoom", 4))
        info = glance.status()

        def frame(src: str, title: str, note: str = "") -> str:
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
            parts.append(
                f"<h2>channel <code>{name}</code></h2>"
                f'<p class="meta">/c/{name}.png &middot; {len(meta["available"])} '
                f"of {meta['configured']} showing &middot; {avail}</p>"
                + frame(f"/c/{name}.png?peek=1", f"{name} (current)")
            )

        def scene_url(sid: str) -> str:
            demo = PREVIEW_DEMO.get(sid)
            return f"/s/{sid}.png?{demo}" if demo else f"/s/{sid}.png"

        scene_frames = "".join(
            frame(scene_url(sid), sid, REGISTRY[sid].description
                  if hasattr(REGISTRY[sid], "description") else "")
            for sid in sorted(REGISTRY) if sid != "static"
        )
        anim_frames = "".join(
            frame(f"/s/marquee.png?{q}", label, "animated png")
            for label, q in PREVIEW_ANIMATIONS
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
 &middot; <a href="{tokened('/api/status')}">status json</a>
 &middot; <a href="{tokened(f'/preview?zoom={3 if zoom != 3 else 5}')}">toggle zoom</a></p>
{"".join(parts) or "<p class='meta'>No channels configured.</p>"}
<h3>All scenes</h3><div class="grid">{scene_frames}</div>
<h3>Animation &mdash; APNG</h3>
<p class="meta">These are animated PNGs. If they move here, your browser
 supports APNG; whether the <em>panel</em> does is the open question &mdash; an
 APNG is a valid PNG, so a decoder that ignores the animation chunks shows
 frame&nbsp;0 and nothing breaks. Point a private app at one to find out.</p>
<div class="grid">{anim_frames}</div>
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
