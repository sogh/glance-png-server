"""Home Assistant entity states."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from glance.scenes import REGISTRY
from glance.sources.homeassistant import Entity, HomeAssistantSource

STATES = [
    {"entity_id": "sensor.greenhouse", "state": "41.2",
     "attributes": {"friendly_name": "Greenhouse Temperature",
                    "unit_of_measurement": "°F", "device_class": "temperature"}},
    {"entity_id": "binary_sensor.barn", "state": "on",
     "attributes": {"friendly_name": "Barn Door", "device_class": "door"}},
    {"entity_id": "sensor.gate_battery", "state": "14",
     "attributes": {"friendly_name": "Gate Battery",
                    "unit_of_measurement": "%", "device_class": "battery"}},
    {"entity_id": "sensor.tractor", "state": "unavailable",
     "attributes": {"friendly_name": "Tractor"}},
]


@pytest.fixture
def primed(tmp_path: Path) -> HomeAssistantSource:
    src = HomeAssistantSource("http://ha.invalid:8123", "tok",
                              cache_dir=tmp_path, refresh=99999)
    src.cache_file.write_text(json.dumps(STATES))
    return src


# --- formatting -------------------------------------------------------------

def test_numbers_carry_their_unit():
    assert Entity("s.a", "41.2", unit="°F").display() == "41°F"
    assert Entity("s.a", "52", unit="psi").display() == "52psi"


def test_small_values_keep_a_decimal():
    assert Entity("s.a", "4.2", unit="°F").display() == "4.2°F"


def test_text_states_are_shortened_and_upper_cased():
    assert Entity("s.a", "drying").display() == "DRYING"
    # Capped at 12: the scene truncates to fit anyway, this just stops an
    # absurd state string from dominating the layout calculation.
    assert Entity("s.a", "needs_cleaning").display() == "NEEDS CLEANI"


def test_unavailable_is_said_not_guessed():
    """HA says 'unavailable' explicitly. Printing the last known value as
    though the sensor were still reporting would be a lie."""
    for dead in ("unavailable", "unknown", ""):
        assert not Entity("s.a", dead).available
        assert Entity("s.a", dead).display() == "--"


# --- what is worth colouring ------------------------------------------------

def test_an_open_door_alerts_and_a_shut_one_does_not():
    assert Entity("b.d", "on", device_class="door").alerting
    assert not Entity("b.d", "off", device_class="door").alerting


def test_a_low_battery_alerts():
    assert Entity("s.b", "14", unit="%", device_class="battery").alerting
    assert not Entity("s.b", "80", unit="%", device_class="battery").alerting


def test_leaks_and_smoke_alert():
    assert Entity("b.m", "on", device_class="moisture").alerting
    assert Entity("b.s", "on", device_class="smoke").alerting


def test_an_ordinary_sensor_never_alerts():
    assert not Entity("s.t", "41.2", device_class="temperature").alerting


def test_an_unavailable_entity_does_not_alert():
    """It is missing, not on fire."""
    assert not Entity("b.d", "unavailable", device_class="door").alerting


# --- the source -------------------------------------------------------------

def test_lookup_and_listing(primed):
    assert primed.get("sensor.greenhouse").name == "Greenhouse Temperature"
    assert primed.get("nothing.here") is None
    assert "binary_sensor.barn" in primed.ids()


def test_labels_can_be_overridden_for_the_panel(primed):
    """A 64px column cannot hold 'Greenhouse Temperature'."""
    picked = primed.pick("sensor.greenhouse=GREENHOUSE, binary_sensor.barn")
    assert [p[2] for p in picked] == ["GREENHOUSE", ""]
    assert picked[0][0].name == "Greenhouse Temperature"


def test_an_unknown_entity_id_survives_as_a_gap(primed):
    picked = primed.pick("sensor.nope")
    assert picked[0][0] is None and picked[0][1] == "sensor.nope"


def test_without_a_token_it_says_so(tmp_path: Path):
    src = HomeAssistantSource("http://ha.invalid:8123", "", cache_dir=tmp_path)
    assert not src.configured
    assert src.all() == []
    assert "token" in src.last_error


def test_a_failed_fetch_serves_the_cache(primed):
    primed.refresh = 0
    primed.timeout = 0.001
    assert primed.get("sensor.greenhouse") is not None
    assert primed.last_error


# --- the scene --------------------------------------------------------------

def render(app, spec, params=None, source=None):
    ctx = app.context(brightness=1.0)
    ctx.homeassistant = source
    return REGISTRY["entities"].render(ctx, {"entities": spec, **(params or {})})


@pytest.fixture
def source(primed):
    return primed


def test_columns_layout(app, source):
    c = render(app, "sensor.greenhouse=GREENHOUSE, sensor.gate_battery=GATE",
               source=source)
    assert c.image.size == (192, 32)
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 100


def test_rows_layout_differs(app, source):
    spec = "sensor.greenhouse=GREENHOUSE, binary_sensor.barn=BARN"
    cols = render(app, spec, source=source)
    rows = render(app, spec, {"layout": "rows"}, source=source)
    assert cols.to_ascii() != rows.to_ascii()


def test_an_alerting_entity_reads_red(app, source):
    c = render(app, "sensor.gate_battery=GATE", source=source)
    reds = [p for p in c.image.get_flattened_data()
            if p[0] > 180 and p[1] < 90 and p[2] < 90]
    assert reds


def test_nothing_is_clipped_at_the_top_row(app, source):
    """The value font sits a row higher than the label, which clipped the
    first row when there was no title above it."""
    c = render(app, "sensor.greenhouse=GREEN, sensor.gate_battery=GATE",
               {"layout": "rows"}, source=source)
    lit_top = [x for x in range(192) if sum(c.image.getpixel((x, 0))) > 0]
    assert c.image.size == (192, 32)
    # Whatever is drawn on row 0 must also appear on row 1: a clipped glyph
    # would have its top row missing entirely.
    assert not lit_top or any(sum(c.image.getpixel((x, 1))) > 0 for x in lit_top)


def test_nothing_overflows(app, source):
    for layout in ("columns", "rows"):
        c = render(app, "sensor.greenhouse=A VERY LONG LABEL INDEED, "
                        "sensor.gate_battery=ANOTHER LONG ONE",
                   {"layout": layout}, source=source)
        edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
        assert all(sum(p) == 0 for p in edge), layout


def test_unconfigured_explains_itself(app):
    ctx = app.context(brightness=1.0)
    ctx.homeassistant = None
    c = REGISTRY["entities"].render(ctx, {"entities": "sensor.x"})
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 0


def test_it_drops_out_of_rotation_when_unconfigured(app, now):
    ctx = app.context(now)
    ctx.homeassistant = None
    assert not REGISTRY["entities"].available(ctx, {"entities": "sensor.x"})
    assert REGISTRY["entities"].available(ctx, {"entities": "sensor.x", "always": True})


# --- recency ----------------------------------------------------------------

def test_ago_never_says_now():
    """The activity scene uses NOW for a zone that is active this instant.
    Two meanings for one word, separated only by colour, is not a distinction
    a glance can make."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    for seconds in (0, 5, 30, 59, 89):
        e = Entity("b.d", "off", last_changed=now - timedelta(seconds=seconds))
        assert e.ago(now) != "NOW", f"{seconds}s ago"
        assert e.ago(now) == "1M"


def test_ago_units():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    def ago(**kw):
        return Entity("b.d", "off", last_changed=now - timedelta(**kw)).ago(now)
    assert ago(minutes=30) == "30M"
    assert ago(hours=5) == "5H"
    assert ago(days=3) == "3D"
    assert Entity("b.d", "off").ago(now) == "--"


def test_zones_rank_by_recency(primed):
    import json
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    states = [
        {"entity_id": "binary_sensor.far", "state": "off",
         "last_changed": (now - timedelta(hours=9)).isoformat(),
         "attributes": {"friendly_name": "Far Field Motion", "device_class": "motion"}},
        {"entity_id": "binary_sensor.near", "state": "off",
         "last_changed": (now - timedelta(minutes=3)).isoformat(),
         "attributes": {"friendly_name": "Driveway Motion", "device_class": "motion"}},
    ]
    primed.cache_file.write_text(json.dumps(states))
    ranked = primed.of_class("motion")
    assert [e.entity_id for e in ranked] == ["binary_sensor.near", "binary_sensor.far"]


def test_unavailable_duplicates_are_dropped(primed):
    """Two integrations can expose the same camera; the dead copy is noise."""
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    primed.cache_file.write_text(json.dumps([
        {"entity_id": "binary_sensor.a", "state": "off", "last_changed": now,
         "attributes": {"friendly_name": "Barn Motion", "device_class": "motion"}},
        {"entity_id": "binary_sensor.b", "state": "unavailable", "last_changed": now,
         "attributes": {"friendly_name": "Barn Motion", "device_class": "motion"}},
    ]))
    assert [e.entity_id for e in primed.of_class("motion")] == ["binary_sensor.a"]


def test_shared_suffixes_are_trimmed():
    from glance.scenes.activity import tidy
    assert tidy("Driveway Motion") == "DRIVEWAY"
    assert tidy("Barn Top View Motion") == "BARN TOP VIEW"
    assert tidy("Sheep  Motion") == "SHEEP"
    assert tidy("Greenhouse") == "GREENHOUSE"


def test_the_activity_scene_renders(app, primed):
    import json
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    primed.cache_file.write_text(json.dumps([
        {"entity_id": f"binary_sensor.z{i}", "state": "on" if i == 0 else "off",
         "last_changed": (now - timedelta(minutes=i * 20)).isoformat(),
         "attributes": {"friendly_name": f"Zone {i} Motion", "device_class": "motion"}}
        for i in range(4)
    ]))
    ctx = app.context(brightness=1.0)
    ctx.homeassistant = primed
    c = REGISTRY["activity"].render(ctx, {})
    assert c.image.size == (192, 32)
    ambers = [p for p in c.image.get_flattened_data()
              if p[0] > 200 and 120 < p[1] < 220 and p[2] < 80]
    assert ambers, "the active zone should stand out"
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_activity_with_no_sensors_says_so(app, tmp_path):
    import json
    from glance.sources.homeassistant import HomeAssistantSource
    src = HomeAssistantSource("http://ha.invalid", "tok", cache_dir=tmp_path, refresh=99999)
    src.cache_file.write_text(json.dumps([]))
    ctx = app.context(brightness=1.0)
    ctx.homeassistant = src
    c = REGISTRY["activity"].render(ctx, {})
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 0
