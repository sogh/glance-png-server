"""Editing the carousel live.

The design promise worth guarding: edits go to data/overrides.json and
settings.yaml is never rewritten.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glance.runtime import GlanceApp
from glance.server import create_app


@pytest.fixture
def client(project: Path) -> TestClient:
    app = create_app(str(project / "config" / "settings.yaml"))
    app.state.glance.carousel.min_advance_interval = 0
    return TestClient(app)


# --- dwell ------------------------------------------------------------------

def test_dwell_holds_an_entry_across_fetches(app, now):
    """The device decides how often it fetches, so holding is the only way to
    control pace."""
    app.set_channel("main", [
        {"ref": "date", "dwell": 3600},
        {"ref": "panels"},
    ])
    keys = [app.carousel.select("main", app.context(now)).key for _ in range(5)]
    assert keys == ["date"] * 5, "a long dwell should pin the entry"


def test_zero_dwell_advances_every_fetch(app, now):
    app.set_channel("main", [{"ref": "date"}, {"ref": "panels"}])
    keys = [app.carousel.select("main", app.context(now)).key for _ in range(4)]
    assert keys == ["date", "panels", "date", "panels"]


def test_dwell_expires_and_then_it_moves_on(app, now, monkeypatch):
    app.set_channel("main", [{"ref": "date", "dwell": 60}, {"ref": "panels"}])
    assert app.carousel.select("main", app.context(now)).key == "date"

    # Pretend the dwell has elapsed.
    state = app.carousel._state["main"]
    state["last_at"] = time.time() - 120
    assert app.carousel.select("main", app.context(now)).key == "panels"


def test_the_debounce_is_a_floor_under_dwell(app, now):
    app.set_channel("main", [{"ref": "date", "dwell": 0}, {"ref": "panels"}])
    # Set after saving: a reload re-reads this from config, by design.
    app.carousel.min_advance_interval = 3600
    keys = [app.carousel.select("main", app.context(now)).key for _ in range(3)]
    assert keys == ["date"] * 3


# --- the overlay ------------------------------------------------------------

def test_editing_never_rewrites_settings_yaml(app, project):
    """settings.yaml is hand-authored with comments; the editor must not touch it."""
    cfg = project / "config" / "settings.yaml"
    before = cfg.read_text()
    app.set_channel("main", [{"ref": "panels"}])
    assert cfg.read_text() == before
    assert (project / "data" / "overrides.json").exists()


def test_overlay_replaces_a_channel_wholesale(app):
    app.set_channel("main", [{"ref": "panels"}])
    assert [e["ref"] for e in app.channel_spec("main")] == ["panels"]


def test_reset_restores_the_file_version(app):
    original = [e["ref"] for e in app.channel_spec("main")]
    app.set_channel("main", [{"ref": "panels"}])
    app.reset_channel("main")
    assert [e["ref"] for e in app.channel_spec("main")] == original


def test_untouched_channels_are_unaffected(app):
    other = [e["ref"] for e in app.channel_spec("gated")]
    app.set_channel("main", [{"ref": "panels"}])
    assert [e["ref"] for e in app.channel_spec("gated")] == other


def test_a_corrupt_overlay_does_not_take_the_panel_down(app, project):
    (project / "data" / "overrides.json").write_text("{ not json")
    app._mtimes = {}                                # force a reload attempt
    assert app.channel_spec("main"), "should fall back to settings.yaml"


def test_edits_survive_a_restart(app, project):
    app.set_channel("main", [{"ref": "panels", "dwell": 45}])
    fresh = GlanceApp.from_config(project / "config" / "settings.yaml")
    assert [e["ref"] for e in fresh.channel_spec("main")] == ["panels"]
    assert fresh.settings.channels["main"][0].dwell == 45


# --- the http api -----------------------------------------------------------

def test_listing_channels(client):
    body = client.get("/api/channels").json()
    assert "main" in body["channels"]
    assert "date" in body["scenes"]
    assert body["carousel"]["mode"] in ("advance", "clock")


def test_getting_one_channel(client):
    body = client.get("/api/channels/main").json()
    assert body["name"] == "main"
    assert body["overridden"] is False
    assert all("ref" in e and "dwell" in e for e in body["entries"])


def test_unknown_channel_is_404(client):
    assert client.get("/api/channels/nope").status_code == 404


def test_put_replaces_and_marks_it_overridden(client):
    r = client.put("/api/channels/main",
                   json={"entries": [{"ref": "date", "dwell": 90}]})
    assert r.status_code == 200
    body = client.get("/api/channels/main").json()
    assert [e["ref"] for e in body["entries"]] == ["date"]
    assert body["entries"][0]["dwell"] == 90
    assert body["overridden"] is True


def test_put_validates_before_saving(client):
    before = client.get("/api/channels/main").json()["entries"]
    r = client.put("/api/channels/main", json={"entries": [{"nonsense": 1}]})
    assert r.status_code == 400
    assert client.get("/api/channels/main").json()["entries"] == before, \
        "a rejected save must not have changed anything"


def test_reset_endpoint(client):
    client.put("/api/channels/main", json={"entries": [{"ref": "panels"}]})
    client.post("/api/channels/main/reset")
    assert client.get("/api/channels/main").json()["overridden"] is False


def test_carousel_settings_can_be_changed(client):
    assert client.put("/api/carousel", json={"mode": "clock", "dwell": 120}).status_code == 200
    body = client.get("/api/channels").json()
    assert body["carousel"]["mode"] == "clock"
    assert body["carousel"]["dwell"] == 120


def test_carousel_mode_is_validated(client):
    assert client.put("/api/carousel", json={"mode": "sideways"}).status_code == 400


def test_a_saved_edit_shows_up_on_the_next_fetch(client):
    client.put("/api/channels/main", json={"entries": [{"ref": "panels"}]})
    assert client.get("/c/main.png").headers["x-glance-scene"] == "panels"


def test_editor_page_loads(client):
    html = client.get("/edit").text
    assert "Carousel editor" in html
    assert "/api/channels" in html


def test_editor_and_its_api_are_gated_by_the_token(tokened_client):
    for path in ("/edit", "/api/channels", "/api/channels/main"):
        assert tokened_client.get(path).status_code == 404, path
    assert tokened_client.put("/api/channels/main",
                              json={"entries": []}).status_code == 404
    assert tokened_client.get(f"/edit?k={TOKEN}").status_code == 200


TOKEN = "s3cr3t-token-value"


@pytest.fixture
def tokened_client(project: Path) -> TestClient:
    import yaml

    cfg = project / "config" / "settings.yaml"
    data = yaml.safe_load(cfg.read_text())
    data.setdefault("server", {})["access_token"] = TOKEN
    cfg.write_text(yaml.safe_dump(data))
    return TestClient(create_app(str(cfg)))


# --- parameter schemas ------------------------------------------------------
# Before these, the editor showed a raw JSON box: the only way to learn what a
# scene accepted was to read its source, and a typo was silently ignored.

def test_every_scene_publishes_its_parameters(client):
    catalogue = {s["id"]: s for s in client.get("/api/channels").json()["catalogue"]}
    assert set(catalogue) >= {"sprite", "weather", "agenda", "date", "pulse"}
    for scene in catalogue.values():
        for param in scene["params"]:
            assert {"name", "type", "default"} <= set(param), scene["id"]


def test_sprite_publishes_the_params_you_would_have_had_to_read_the_source_for(client):
    catalogue = {s["id"]: s for s in client.get("/api/channels").json()["catalogue"]}
    names = {p["name"] for p in catalogue["sprite"]["params"]}
    assert {"before", "after", "sprite", "gap", "sprite_scale"} <= names


def test_dynamic_options_are_resolved_to_live_values(client):
    catalogue = {s["id"]: s for s in client.get("/api/channels").json()["catalogue"]}
    by_name = {p["name"]: p for p in catalogue["sprite"]["params"]}
    assert "sweatpants" in by_name["sprite"]["options"]
    assert "5x7" in by_name["font"]["options"]
    assert "amber" in by_name["color"]["options"]


def test_select_options_never_leak_a_marker(client):
    for scene in client.get("/api/channels").json()["catalogue"]:
        for param in scene["params"]:
            assert not isinstance(param["options"], str), \
                f"{scene['id']}.{param['name']} still says {param['options']}"


def test_a_mistyped_param_is_reported_on_save(client):
    r = client.put("/api/channels/main", json={"entries": [
        {"ref": "sprite", "params": {"befoer": "It's"}}]})
    assert r.status_code == 200, "saved anyway, since old configs may carry one"
    assert any("befoer" in w for w in r.json()["warnings"])


def test_an_out_of_range_value_is_reported(client):
    r = client.put("/api/channels/main", json={"entries": [
        {"ref": "sprite", "params": {"gap": 9999}}]})
    assert any("gap" in w for w in r.json()["warnings"])


def test_a_value_outside_a_select_is_reported(client):
    r = client.put("/api/channels/main", json={"entries": [
        {"ref": "sprite", "params": {"font": "comic-sans"}}]})
    assert any("font" in w for w in r.json()["warnings"])


def test_a_correct_save_warns_about_nothing(client):
    r = client.put("/api/channels/main", json={"entries": [
        {"ref": "sprite", "params": {"before": "It's", "after": "season!", "gap": 6}}]})
    assert r.json()["warnings"] == []


def test_common_params_are_offered_on_every_scene(client):
    for scene in client.get("/api/channels").json()["catalogue"]:
        assert "always" in {p["name"] for p in scene["params"]}, scene["id"]


def test_the_editor_page_no_longer_ships_a_raw_json_box_for_params(client):
    html = client.get("/edit").text
    assert "catalogue" in html
    assert "params (json)" not in html


def test_the_deploy_never_ships_the_overlay():
    """A laptop's overrides.json overwriting the server's silently discards
    every channel change made from the editor. It did, once."""
    from pathlib import Path
    script = Path(__file__).resolve().parent.parent / "deploy" / "pve-deploy.sh"
    text = script.read_text()
    assert "--exclude './data/overrides.json'" in text
    assert "--exclude './data/state.json'" in text
    assert "--exclude './data/cache'" in text


def test_the_deploy_excludes_the_reminders_file_under_both_names():
    """It was renamed from todos.json; an exclusion that stops matching is
    indistinguishable from no exclusion at all."""
    from pathlib import Path
    script = Path(__file__).resolve().parent.parent / "deploy" / "pve-deploy.sh"
    text = script.read_text()
    assert "--exclude './data/reminders.json'" in text
    assert "--exclude './data/todos.json'" in text
