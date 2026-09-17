"""Editing reminders: the store, the routes, and the round trip to the panel."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from glance import todostore
from glance.server import create_app
from glance.sources.todos import TodoSource
from glance.todostore import TodoError

TODAY = date(2026, 9, 17)


@pytest.fixture
def client(project: Path) -> TestClient:
    return TestClient(create_app(str(project / "config" / "settings.yaml")))


# --- normalising ------------------------------------------------------------

def test_a_bare_string_becomes_a_reminder():
    item = todostore.normalise("Water ferns")
    assert item["text"] == "Water ferns"
    assert item["priority"] == 3 and item["done"] is False and item["due"] == ""
    assert item["id"]


def test_title_is_accepted_as_an_alias_for_text():
    assert todostore.normalise({"title": "Renew passport"})["text"] == "Renew passport"


def test_keys_this_module_does_not_know_are_carried_through():
    """A hand-written file keeps whatever else someone put in it."""
    item = todostore.normalise({"text": "Call back", "notes": "after 6", "url": "x"})
    assert item["notes"] == "after 6" and item["url"] == "x"


def test_control_characters_are_stripped():
    item = todostore.normalise({"text": "line\x00one\ntwo"}, strict=True)
    assert "\x00" not in item["text"] and "\n" not in item["text"]


@pytest.mark.parametrize("fields, message", [
    ({"text": ""}, "cannot be empty"),
    ({"text": "x" * 200}, "longer than"),
    ({"text": "ok", "due": "next tuesday"}, "must be a date"),
    ({"text": "ok", "priority": "soon"}, "whole number"),
    ({"text": "ok", "priority": 9}, "between"),
])
def test_input_from_the_api_is_refused_with_a_reason(fields, message):
    with pytest.raises(TodoError, match=message):
        todostore.normalise(fields, strict=True)


def test_what_is_already_in_the_file_is_coerced_rather_than_refused():
    """A typo in a hand-written date must not lock the whole page."""
    item = todostore.normalise({"text": "x" * 200, "due": "whenever", "priority": "high"})
    assert len(item["text"]) == todostore.MAX_TEXT
    assert item["due"] == "" and item["priority"] == 3


# --- the file ---------------------------------------------------------------

def test_writes_are_atomic(tmp_path: Path):
    path = tmp_path / "reminders.json"
    todostore.add(path, {"text": "Feed the cat"})
    assert not list(tmp_path.glob("*.tmp"))


def test_ids_are_minted_once_and_then_stick(tmp_path: Path):
    """Reinventing ids on every read would make an edit address the wrong row."""
    path = tmp_path / "reminders.json"
    path.write_text(json.dumps(["Water ferns", {"text": "Call back"}]))

    first = todostore.listing(path)
    assert all(item["id"] for item in first)
    assert [item["id"] for item in todostore.listing(path)] == [i["id"] for i in first]
    assert all(entry["id"] for entry in json.loads(path.read_text()))


def test_the_todos_wrapper_shape_is_preserved(tmp_path: Path):
    path = tmp_path / "reminders.json"
    path.write_text(json.dumps({"todos": [{"text": "Water ferns"}]}))
    todostore.add(path, {"text": "Feed the cat"})
    written = json.loads(path.read_text())
    assert isinstance(written, dict) and len(written["todos"]) == 2


def test_a_broken_file_says_so_rather_than_being_overwritten(tmp_path: Path):
    path = tmp_path / "reminders.json"
    path.write_text("{ not json")
    with pytest.raises(TodoError, match="not valid JSON"):
        todostore.listing(path)
    assert path.read_text() == "{ not json"


def test_a_read_only_data_dir_does_not_blow_up_a_listing(tmp_path: Path):
    if os.geteuid() == 0:
        pytest.skip("root ignores the mode bits")
    path = tmp_path / "reminders.json"
    path.write_text(json.dumps(["Water ferns"]))        # no ids, so it wants to heal
    tmp_path.chmod(0o555)
    try:
        assert [i["text"] for i in todostore.listing(path)] == ["Water ferns"]
    finally:
        tmp_path.chmod(0o755)


# --- add, update, remove ----------------------------------------------------

def test_add_update_remove(tmp_path: Path):
    path = tmp_path / "reminders.json"
    item = todostore.add(path, {"text": "Feed the cat", "due": "2026-09-20"})

    edited = todostore.update(path, item["id"], {"done": True})
    assert edited["done"] is True
    assert edited["text"] == "Feed the cat", "a partial update must not clear the rest"
    assert edited["due"] == "2026-09-20"

    assert todostore.remove(path, item["id"]) is True
    assert todostore.remove(path, item["id"]) is False
    assert todostore.listing(path) == []


def test_updating_something_absent_raises(tmp_path: Path):
    with pytest.raises(KeyError):
        todostore.update(tmp_path / "reminders.json", "nope", {"text": "hi"})


def test_an_id_in_the_body_cannot_reassign_a_row(tmp_path: Path):
    path = tmp_path / "reminders.json"
    a = todostore.add(path, {"text": "first"})
    b = todostore.add(path, {"text": "second"})
    todostore.update(path, a["id"], {"id": b["id"], "text": "renamed"})
    by_id = {i["id"]: i["text"] for i in todostore.listing(path)}
    assert by_id[a["id"]] == "renamed" and by_id[b["id"]] == "second"


def test_the_list_is_capped(tmp_path: Path):
    path = tmp_path / "reminders.json"
    todostore.write(path, [todostore.normalise(f"item {n}")
                           for n in range(todostore.MAX_ITEMS)])
    with pytest.raises(TodoError, match="delete some first"):
        todostore.add(path, {"text": "one too many"})


# --- the point of the whole thing -------------------------------------------

def test_a_write_reaches_the_panel_without_a_restart(tmp_path: Path):
    path = tmp_path / "reminders.json"
    todostore.write(path, [])
    source = TodoSource(path)
    assert source.open_items(TODAY) == []

    todostore.add(path, {"text": "Feed the cat"})
    assert [t.text for t in source.open_items(TODAY)] == ["Feed the cat"]

    todostore.write(path, [])
    assert source.open_items(TODAY) == []


def test_done_takes_a_row_off_the_panel_but_keeps_it_in_the_file(tmp_path: Path):
    path = tmp_path / "reminders.json"
    item = todostore.add(path, {"text": "Water ferns"})
    todostore.update(path, item["id"], {"done": True})
    assert TodoSource(path).open_items(TODAY) == []
    assert [i["text"] for i in todostore.listing(path)] == ["Water ferns"]


# --- over http --------------------------------------------------------------

def test_http_round_trip(client):
    created = client.post("/api/reminders", json={"text": "Feed the cat"})
    assert created.status_code == 200, created.text
    ident = created.json()["item"]["id"]

    assert "Feed the cat" in [i["text"] for i in client.get("/api/reminders").json()["items"]]

    edited = client.put(f"/api/reminders/{ident}", json={"priority": 1})
    assert edited.json()["item"]["priority"] == 1
    assert edited.json()["item"]["text"] == "Feed the cat"

    assert client.delete(f"/api/reminders/{ident}").status_code == 200
    assert "Feed the cat" not in [i["text"] for i in client.get("/api/reminders").json()["items"]]


def test_http_rejects_bad_input_with_a_reason(client):
    r = client.post("/api/reminders", json={"text": "ok", "due": "soonish"})
    assert r.status_code == 400
    assert "must be a date" in r.json()["detail"]


def test_http_404s_on_something_absent(client):
    assert client.put("/api/reminders/nope", json={"text": "x"}).status_code == 404
    assert client.delete("/api/reminders/nope").status_code == 404


def test_reminder_endpoints_are_gated_by_the_token(project: Path):
    cfg = project / "config" / "settings.yaml"
    data = yaml.safe_load(cfg.read_text())
    data.setdefault("server", {})["access_token"] = "tok"
    cfg.write_text(yaml.safe_dump(data))
    c = TestClient(create_app(str(cfg)))

    assert c.get("/api/reminders").status_code == 404
    assert c.post("/api/reminders", json={"text": "x"}).status_code == 404
    assert c.delete("/api/reminders/anything").status_code == 404
    assert c.get("/api/reminders?k=tok").status_code == 200


def test_the_editor_has_a_reminder_control(client):
    html = client.get("/edit").text
    assert 'id="remadd"' in html and "/api/reminders" in html
