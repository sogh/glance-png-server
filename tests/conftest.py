from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glance.config import load_settings  # noqa: E402
from glance.runtime import GlanceApp  # noqa: E402

TZ = ZoneInfo("America/Los_Angeles")

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:standup@test
DTSTART;TZID=America/Los_Angeles:20260907T093000
DTEND;TZID=America/Los_Angeles:20260907T094500
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
SUMMARY:Team standup
LOCATION:Zoom
END:VEVENT
BEGIN:VEVENT
UID:dentist@test
DTSTART;TZID=America/Los_Angeles:20260908T143000
DTEND;TZID=America/Los_Angeles:20260908T153000
SUMMARY:Dentist
END:VEVENT
BEGIN:VEVENT
UID:allday@test
DTSTART;VALUE=DATE:20260910
DTEND;VALUE=DATE:20260911
SUMMARY:Anna birthday
END:VEVENT
BEGIN:VEVENT
UID:utc@test
DTSTART:20260909T170000Z
DTEND:20260909T180000Z
SUMMARY:Quarterly review
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def now() -> datetime:
    """Tue 8 Sep 2026, 08:00 local -- before that day's standup."""
    return datetime(2026, 9, 8, 8, 0, tzinfo=TZ)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A self-contained project tree: config, holidays, todos, static art."""
    (tmp_path / "config").mkdir()
    (tmp_path / "data" / "cache").mkdir(parents=True)
    (tmp_path / "assets" / "static").mkdir(parents=True)

    settings = {
        "timezone": "America/Los_Angeles",
        "panel": {"width": 192},
        "carousel": {"mode": "advance"},
        "sources": {"todos": {"path": str(tmp_path / "data" / "todos.json")}},
        "paths": {
            "state_file": str(tmp_path / "data" / "state.json"),
            "static_dir": str(tmp_path / "assets" / "static"),
            "cache_dir": str(tmp_path / "data" / "cache"),
            "holidays_file": str(tmp_path / "config" / "holidays.yaml"),
        },
        "channels": {
            "main": [
                {"scene": "holiday", "takeover": True},
                {"scene": "todos", "params": {"count": 3}},
                {"scene": "clock"},
            ],
            "gated": [
                {"scene": "clock", "when": {"hours": {"from": 20, "to": 23}}},
                {"scene": "blank"},
            ],
        },
    }
    (tmp_path / "config" / "settings.yaml").write_text(yaml.safe_dump(settings))
    (tmp_path / "config" / "holidays.yaml").write_text(
        yaml.safe_dump(
            [
                {"name": "Christmas", "date": "12-25", "window": 14, "after": 1,
                 "color": "green", "accent": "red", "countdown": True},
                {"name": "Thanksgiving", "rule": {"nth": 4, "weekday": "thu", "month": 11},
                 "window": 5},
            ]
        )
    )
    (tmp_path / "data" / "todos.json").write_text(
        json.dumps(
            [
                {"text": "Renew passport", "due": "2026-09-11", "priority": 1},
                {"text": "Water ferns", "priority": 3, "tag": "home"},
                {"text": "Already done", "done": True},
            ]
        )
    )
    return tmp_path


@pytest.fixture
def app(project: Path) -> GlanceApp:
    return GlanceApp(load_settings(project / "config" / "settings.yaml"))


@pytest.fixture(scope="session")
def ics_server(tmp_path_factory):
    """A real HTTP server for the ICS fixture -- exercises the fetch path too."""
    import socketserver
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    root = tmp_path_factory.mktemp("ics")
    (root / "test.ics").write_text(ICS)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    class Server(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer.server_bind calls socket.getfqdn(), which on macOS
            # blocks on a reverse-DNS lookup for ~35s. We know the hostname.
            socketserver.TCPServer.server_bind(self)
            self.server_name = "127.0.0.1"
            self.server_port = self.server_address[1]

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/test.ics"
    server.shutdown()
    server.server_close()
