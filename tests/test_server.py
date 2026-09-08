from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from glance.server import create_app


@pytest.fixture
def client(project: Path) -> TestClient:
    app = create_app(str(project / "config" / "settings.yaml"))
    app.state.glance.carousel.min_advance_interval = 0
    return TestClient(app)


def as_image(response) -> Image.Image:
    return Image.open(BytesIO(response.content))


def test_health(client):
    body = client.get("/healthz").json()
    assert body["ok"] and "main" in body["channels"]


def test_channel_serves_a_panel_sized_png(client):
    r = client.get("/c/main.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert as_image(r).size == (192, 32)


def test_the_extension_is_optional(client):
    """The docs note the url does not need a .png ending."""
    assert as_image(client.get("/c/main")).size == (192, 32)


def test_responses_are_never_cached(client):
    """Any caching in front of us would freeze the carousel on one frame."""
    headers = client.get("/c/main.png").headers
    assert "no-store" in headers["cache-control"]


def test_successive_fetches_rotate(client):
    seen = [client.get("/c/main.png").headers["x-glance-scene"] for _ in range(4)]
    assert len(set(seen)) > 1
    assert seen[0] == seen[2] and seen[1] == seen[3]


def test_position_header_reports_where_we_are(client):
    assert client.get("/c/main.png").headers["x-glance-position"] == "1/2"


def test_peek_does_not_advance_the_rotation(client):
    first = client.get("/c/main.png?peek=1").headers["x-glance-scene"]
    for _ in range(3):
        assert client.get("/c/main.png?peek=1").headers["x-glance-scene"] == first


def test_a_single_scene_can_be_pinned(client):
    r = client.get("/s/clock.png")
    assert r.status_code == 200 and as_image(r).size == (192, 32)


def test_scene_params_come_from_the_query_string(client):
    a = client.get("/s/text.png?text=HELLO").content
    b = client.get("/s/text.png?text=GOODBYE").content
    assert a != b


def test_static_art_is_addressable_by_filename(client, project):
    Image.new("RGB", (192, 32), (0, 128, 255)).save(
        project / "assets" / "static" / "art.png"
    )
    img = as_image(client.get("/s/static:art.png"))
    assert img.convert("RGB").getpixel((96, 16)) == (0, 128, 255)


def test_oversized_art_is_scaled_to_the_panel(client, project):
    Image.new("RGB", (1920, 320), (255, 0, 0)).save(
        project / "assets" / "static" / "big.png"
    )
    assert as_image(client.get("/s/static:big.png")).size == (192, 32)


def test_an_unknown_scene_draws_an_error_card_rather_than_failing(client):
    """A 500 leaves the device showing its last cached frame, which is
    indistinguishable from everything working."""
    r = client.get("/s/does-not-exist.png")
    assert r.status_code == 200
    assert as_image(r).size == (192, 32)
    assert "missing" in r.headers["x-glance-scene"]


def test_a_scene_that_raises_still_returns_a_png(client, monkeypatch):
    from glance.scenes import REGISTRY

    def boom(ctx, params):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(REGISTRY["clock"], "render_fn", boom)
    r = client.get("/s/clock.png")
    assert r.status_code == 200
    assert as_image(r).size == (192, 32)
    assert r.headers["x-glance-scene"].startswith("error:")


def test_an_unknown_channel_draws_an_error_card(client):
    r = client.get("/c/nope.png")
    assert r.status_code == 200 and as_image(r).size == (192, 32)


def test_a_channel_with_nothing_available_falls_back(client, project):
    import yaml

    cfg = project / "config" / "settings.yaml"
    data = yaml.safe_load(cfg.read_text())
    data["channels"]["empty"] = [{"scene": "agenda"}]     # no ics url configured
    cfg.write_text(yaml.safe_dump(data))

    app = create_app(str(cfg))
    r = TestClient(app).get("/c/empty.png")
    assert r.status_code == 200
    assert r.headers["x-glance-scene"].startswith("fallback:")


def test_status_reports_why_a_scene_is_or_is_not_showing(client):
    body = client.get("/api/status").json()
    assert body["panel"] == {"width": 192, "height": 32}
    assert body["channels"]["main"]["available"] == ["todos(count=3)", "clock"]
    assert body["sources"]["todos"]["open"] == 2
    assert "clock" in body["scenes"]


def test_reset_rewinds_the_rotation(client):
    client.get("/c/main.png")
    client.get("/c/main.png")
    assert client.post("/api/reset/main").json() == {"reset": "main"}
    assert client.get("/c/main.png").headers["x-glance-position"] == "1/2"


def test_preview_page_renders(client):
    r = client.get("/preview")
    assert r.status_code == 200
    assert "/c/main.png?peek=1" in r.text


def test_root_redirects_to_the_preview(client):
    assert client.get("/", follow_redirects=False).status_code in (302, 307)


def test_every_served_png_stays_well_under_the_one_megabyte_cap(client):
    for path in ("/c/main.png", "/s/clock.png", "/s/todos.png", "/s/countdown.png"):
        assert len(client.get(path).content) < 100_000


# --- optional access token -------------------------------------------------
# Only relevant when the server is exposed beyond the LAN, which the Glance
# setup app can force by refusing to verify private addresses.

TOKEN = "s3cr3t-token-value"


@pytest.fixture
def tokened_client(project: Path) -> TestClient:
    import yaml

    cfg = project / "config" / "settings.yaml"
    data = yaml.safe_load(cfg.read_text())
    data.setdefault("server", {})["access_token"] = TOKEN
    cfg.write_text(yaml.safe_dump(data))
    app = create_app(str(cfg))
    app.state.glance.carousel.min_advance_interval = 0
    return TestClient(app)


def test_without_a_token_everything_stays_open(client):
    assert client.get("/c/main.png").status_code == 200
    assert client.get("/preview").status_code == 200
    assert client.get("/api/status").status_code == 200


def test_image_route_requires_the_token(tokened_client):
    assert tokened_client.get("/c/main.png").status_code == 404
    assert tokened_client.get(f"/c/main.png?k={TOKEN}").status_code == 200


def test_a_wrong_token_is_indistinguishable_from_a_missing_channel(tokened_client):
    """404 not 403 -- a stranger should not learn which channels exist."""
    bad = tokened_client.get("/c/main.png?k=wrong")
    missing = tokened_client.get(f"/c/no-such-channel-at-all.png?k=wrong")
    assert bad.status_code == missing.status_code == 404


def test_the_token_may_travel_in_a_header(tokened_client):
    r = tokened_client.get("/c/main.png", headers={"X-Glance-Token": TOKEN})
    assert r.status_code == 200
    assert as_image(r).size == (192, 32)


def test_scene_preview_and_status_are_all_gated(tokened_client):
    for path in ("/s/clock.png", "/preview", "/api/status"):
        assert tokened_client.get(path).status_code == 404, path
        assert tokened_client.get(f"{path}?k={TOKEN}").status_code == 200, path


def test_reset_is_gated(tokened_client):
    assert tokened_client.post("/api/reset/main").status_code == 404
    assert tokened_client.post(f"/api/reset/main?k={TOKEN}").status_code == 200


def test_healthz_stays_open_but_stops_naming_channels(tokened_client):
    """Uptime checks keep working, but the response stops describing the
    configuration. (Deliberately does not also take the plain `client`
    fixture -- both share one settings file, and whichever is built second
    would see the other's config.)"""
    gated = tokened_client.get("/healthz")
    assert gated.status_code == 200
    assert gated.json() == {"ok": True}
    assert "channels" not in gated.json()


def test_the_preview_page_carries_the_token_into_its_image_urls(tokened_client):
    html = tokened_client.get(f"/preview?k={TOKEN}").text
    assert f"/c/main.png?peek=1&k={TOKEN}" in html
    assert f"/api/status?k={TOKEN}" in html
    # The zoom link must not drop it, or the page 404s on itself.
    assert f"/preview?zoom=" in html and html.count(f"k={TOKEN}") > 3


def test_the_token_is_not_leaked_into_scene_params(tokened_client):
    """?k= must be stripped before params reach a scene, or 'text' scenes
    would render it onto the panel."""
    a = tokened_client.get(f"/s/text.png?text=HELLO&k={TOKEN}")
    b = tokened_client.get(f"/s/text.png?text=HELLO&k={TOKEN}&_=123")
    assert a.status_code == 200
    assert a.content == b.content, "cache-buster and token must not change the render"
