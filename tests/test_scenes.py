from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from glance.scenes import REGISTRY

TZ = ZoneInfo("America/Los_Angeles")


def pixels(canvas) -> list[tuple[int, int, int]]:
    return list(canvas.image.get_flattened_data())


def lit(canvas) -> int:
    return sum(1 for p in pixels(canvas) if sum(p) > 0)


@pytest.mark.parametrize("scene_id", [s for s in sorted(REGISTRY) if s != "static"])
def test_every_scene_renders_a_correctly_sized_panel(app, now, scene_id):
    rendered, label = app.render_scene(scene_id, {}, app.context(now))
    # A scene may return a Canvas or a Frames; both must be panel-sized.
    canvas = getattr(rendered, "canvases", [rendered])[0]
    assert canvas.image.size == (192, 32)
    assert not label.startswith("error:"), f"{scene_id} raised"
    assert app.png(rendered).startswith(b"\x89PNG\r\n\x1a\n")


def test_scenes_report_availability_honestly(app, now):
    ctx = app.context(now)
    assert REGISTRY["todos"].available(ctx, {})           # fixture has open todos
    assert not REGISTRY["holiday"].available(ctx, {})     # not a holiday in September
    assert not REGISTRY["agenda"].available(ctx, {})      # no ics url configured
    assert REGISTRY["clock"].available(ctx, {})           # always


def test_todos_becomes_unavailable_once_the_list_is_clear(app, now, project):
    (project / "data" / "todos.json").write_text(json.dumps([{"text": "x", "done": True}]))
    assert not REGISTRY["todos"].available(app.context(now), {})


def test_todo_rows_are_drawn(app, now):
    canvas, _ = app.render_scene("todos", {"count": 3}, app.context(now))
    assert lit(canvas) > 100


def test_an_overdue_todo_is_drawn_in_red(app, project):
    (project / "data" / "todos.json").write_text(
        json.dumps([{"text": "Late thing", "due": "2026-09-01"}])
    )
    ctx = app.context(datetime(2026, 9, 8, 9, 0, tzinfo=TZ))
    canvas, _ = app.render_scene("todos", {"count": 1}, ctx)
    reds = [p for p in pixels(canvas) if p[0] > 150 and p[1] < 90 and p[2] < 90]
    assert reds, "overdue rows should read as red"


def test_a_very_long_todo_is_truncated_rather_than_clipped(app, project, now):
    text = "A preposterously long errand that could never fit on one row"
    (project / "data" / "todos.json").write_text(json.dumps([{"text": text}]))
    canvas, _ = app.render_scene("todos", {"count": 1}, app.context(now))

    # Rows 0-6 hold the header and its full-width rule; the item rows below it
    # must stop short of the final column rather than running off the panel.
    item_rows = [canvas.image.getpixel((191, y)) for y in range(9, 32)]
    assert all(sum(p) == 0 for p in item_rows), "text should stop before the last column"

    from glance.fonts import FONT_5X7
    assert FONT_5X7.truncate(text, 186).endswith("…"), "and should be visibly truncated"


def test_todo_tag_filter(app, now):
    ctx = app.context(now)
    assert REGISTRY["todos"].available(ctx, {"tag": "home"})
    assert not REGISTRY["todos"].available(ctx, {"tag": "nonexistent"})


def test_holiday_takes_over_inside_its_window(app):
    ctx = app.context(datetime(2026, 12, 20, 9, 0, tzinfo=TZ))
    assert REGISTRY["holiday"].available(ctx, {})
    canvas, _ = app.render_scene("holiday", {}, ctx)
    greens = [p for p in pixels(canvas) if p[1] > 150 and p[0] < 100]
    assert greens, "Christmas is configured green"


def test_holiday_uses_bespoke_art_when_provided(app, project):
    import yaml
    from PIL import Image

    Image.new("RGB", (192, 32), (7, 3, 250)).save(project / "assets" / "static" / "xmas.png")
    hol = project / "config" / "holidays.yaml"
    data = yaml.safe_load(hol.read_text())
    data[0]["image"] = "xmas"
    hol.write_text(yaml.safe_dump(data))

    ctx = app.context(datetime(2026, 12, 25, 9, 0, tzinfo=TZ))
    canvas, _ = app.render_scene("holiday", {}, ctx)
    assert canvas.image.getpixel((5, 5)) == (7, 3, 250)


def test_countdown_needs_a_date(app, now):
    canvas, label = app.render_scene("countdown", {}, app.context(now))
    assert canvas.image.size == (192, 32) and not label.startswith("error:")


def test_countdown_counts_down(app, now):
    ctx = app.context(now)
    a, _ = app.render_scene("countdown", {"date": "2026-09-18", "label": "TRIP"}, ctx)
    b, _ = app.render_scene("countdown", {"date": "2026-09-19", "label": "TRIP"}, ctx)
    assert a.to_ascii() != b.to_ascii()


def test_static_scene_reports_missing_files(app, now):
    ctx = app.context(now)
    assert not REGISTRY["static"].available(ctx, {"name": "nope"})
    canvas, _ = app.render_scene("static:nope", {}, ctx)
    assert lit(canvas) > 0, "should draw a 'missing' notice"


def test_static_art_hot_reloads_when_the_file_changes(app, now, project):
    import os, time

    from PIL import Image

    path = project / "assets" / "static" / "sign.png"
    Image.new("RGB", (192, 32), (10, 20, 30)).save(path)
    ctx = app.context(now)
    first, _ = app.render_scene("static:sign", {}, ctx)
    assert first.image.getpixel((0, 0)) == (10, 20, 30)

    Image.new("RGB", (192, 32), (200, 100, 50)).save(path)
    os.utime(path, (time.time() + 10, time.time() + 10))
    second, _ = app.render_scene("static:sign", {}, ctx)
    assert second.image.getpixel((0, 0)) == (200, 100, 50)


# --- agenda needs a calendar, so it gets its own wiring ---------------------

@pytest.fixture
def cal_app(project, ics_server):
    import yaml

    from glance.config import load_settings
    from glance.runtime import GlanceApp

    cfg = project / "config" / "settings.yaml"
    data = yaml.safe_load(cfg.read_text())
    data["sources"]["calendar"] = {"ics_url": ics_server, "refresh": 0}
    cfg.write_text(yaml.safe_dump(data))
    return GlanceApp(load_settings(cfg))


def test_agenda_hero_shows_the_next_event(cal_app, now):
    ctx = cal_app.context(now)
    assert REGISTRY["agenda"].available(ctx, {})
    canvas, _ = cal_app.render_scene("agenda", {}, ctx)
    assert lit(canvas) > 200


def test_agenda_marks_an_event_that_is_happening_now(cal_app):
    during = datetime(2026, 9, 8, 9, 35, tzinfo=TZ)
    before = datetime(2026, 9, 8, 8, 0, tzinfo=TZ)
    a, _ = cal_app.render_scene("agenda", {}, cal_app.context(during))
    b, _ = cal_app.render_scene("agenda", {}, cal_app.context(before))
    assert a.to_ascii() != b.to_ascii()
    greens = [p for p in pixels(a) if p[1] > 120 and p[0] < 90]
    assert greens, "an in-progress event should read green"


def test_agenda_list_mode_stacks_several_events(cal_app, now):
    ctx = cal_app.context(now)
    one, _ = cal_app.render_scene("agenda", {"count": 1}, ctx)
    three, _ = cal_app.render_scene("agenda", {"count": 3}, ctx)
    assert one.to_ascii() != three.to_ascii()


def test_agenda_handles_an_all_day_event(cal_app):
    ctx = cal_app.context(datetime(2026, 9, 9, 23, 0, tzinfo=TZ))
    canvas, label = cal_app.render_scene("agenda", {}, ctx)
    assert not label.startswith("error:") and lit(canvas) > 100


def test_agenda_respects_the_24_hour_setting(cal_app, now):
    ctx = cal_app.context(now)
    a, _ = cal_app.render_scene("agenda", {"hour24": False}, ctx)
    b, _ = cal_app.render_scene("agenda", {"hour24": True}, ctx)
    assert a.to_ascii() != b.to_ascii()


def test_always_keeps_an_empty_todo_list_in_the_rotation(app, now, project):
    """Without it the slot drops out and falls through to the channel
    fallback; with it the scene draws its own 'all clear'."""
    (project / "data" / "todos.json").write_text(json.dumps([{"text": "x", "done": True}]))
    ctx = app.context(now)
    assert not REGISTRY["todos"].available(ctx, {})
    assert REGISTRY["todos"].available(ctx, {"always": True})
    canvas, label = app.render_scene("todos", {"always": True}, ctx)
    assert not label.startswith("error:") and lit(canvas) > 0


def test_always_keeps_an_empty_agenda_in_the_rotation(app, now):
    ctx = app.context(now)                      # no calendar configured
    assert not REGISTRY["agenda"].available(ctx, {})
    assert REGISTRY["agenda"].available(ctx, {"always": True})
    canvas, label = app.render_scene("agenda", {"always": True}, ctx)
    assert not label.startswith("error:") and lit(canvas) > 0
