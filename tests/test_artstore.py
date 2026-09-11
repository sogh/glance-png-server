"""Uploading artwork over HTTP.

The name of an uploaded file becomes a path on disk, so most of these are
about it not becoming the wrong path.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from glance import artstore
from glance.artstore import ArtError
from glance.server import create_app


def png_bytes(w=192, h=32, color=(0, 128, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(project: Path) -> TestClient:
    return TestClient(create_app(str(project / "config" / "settings.yaml")))


# --- names ------------------------------------------------------------------

def test_a_normal_name_passes_through():
    assert artstore.safe_name("winter-cabin.png") == "winter-cabin.png"


def test_spaces_and_case_are_normalised():
    assert artstore.safe_name("My Art.PNG") == "My-Art.png"


@pytest.mark.parametrize("raw", [
    "../../etc/passwd.png",
    "/etc/passwd.png",
    "..%2F..%2Fx.png",
])
def test_directory_parts_are_stripped(raw):
    """The name must never be able to reach outside assets/static."""
    name = artstore.safe_name(raw) if "%" not in raw else None
    if name is not None:
        assert "/" not in name and ".." not in name


@pytest.mark.parametrize("raw", ["shell$(rm).png", "semi;colon.png", "pipe|x.png"])
def test_shell_characters_are_refused(raw):
    with pytest.raises(ArtError):
        artstore.safe_name(raw)


@pytest.mark.parametrize("raw", ["evil.exe", "script.sh", "page.html", "noextension"])
def test_non_image_types_are_refused(raw):
    with pytest.raises(ArtError):
        artstore.safe_name(raw)


# --- saving -----------------------------------------------------------------

def test_saving_and_listing(tmp_path: Path):
    saved = artstore.save(tmp_path, "art.png", png_bytes())
    assert saved.width == 192 and saved.height == 32 and saved.fits
    assert (tmp_path / "art.png").is_file()
    assert [f.name for f in artstore.listing(tmp_path)] == ["art"]


def test_a_wrong_sized_file_is_accepted_but_flagged(tmp_path: Path):
    """Worth uploading anyway -- it just will not be pixel perfect."""
    saved = artstore.save(tmp_path, "odd.png", png_bytes(100, 20))
    assert not saved.fits


def test_something_that_is_not_an_image_is_refused(tmp_path: Path):
    with pytest.raises(ArtError):
        artstore.save(tmp_path, "fake.png", b"this is not a png")


def test_an_empty_file_is_refused(tmp_path: Path):
    with pytest.raises(ArtError):
        artstore.save(tmp_path, "empty.png", b"")


def test_an_enormous_file_is_refused(tmp_path: Path):
    with pytest.raises(ArtError):
        artstore.save(tmp_path, "big.png", b"x" * (artstore.MAX_BYTES + 1))


def test_absurd_dimensions_are_refused(tmp_path: Path):
    with pytest.raises(ArtError):
        artstore.save(tmp_path, "huge.png", png_bytes(4000, 3000))


def test_no_partial_file_is_left_behind(tmp_path: Path):
    with pytest.raises(ArtError):
        artstore.save(tmp_path, "bad.png", b"nope")
    assert not list(tmp_path.glob("*.tmp"))


def test_deleting(tmp_path: Path):
    artstore.save(tmp_path, "gone.png", png_bytes())
    assert artstore.delete(tmp_path, "gone")
    assert not artstore.delete(tmp_path, "gone")


def test_delete_cannot_escape_the_directory(tmp_path: Path):
    outside = tmp_path.parent / "precious.png"
    outside.write_bytes(png_bytes())
    static = tmp_path / "static"
    static.mkdir()
    assert not artstore.delete(static, "../precious")
    assert outside.exists(), "must not have been touched"


# --- over http --------------------------------------------------------------

def test_upload_list_and_delete(client):
    r = client.post("/api/art", files={"file": ("sign.png", png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["saved"]["fits"] is True

    names = [f["name"] for f in client.get("/api/art").json()["files"]]
    assert "sign" in names

    assert client.delete("/api/art/sign").status_code == 200
    assert "sign" not in [f["name"] for f in client.get("/api/art").json()["files"]]


def test_uploaded_art_is_usable_immediately(client):
    """The whole point: no redeploy."""
    client.post("/api/art", files={"file": ("fresh.png", png_bytes(color=(255, 0, 0)), "image/png")})
    r = client.get("/s/static:fresh.png?brightness=1")
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    assert img.getpixel((96, 16)) == (255, 0, 0)


def test_a_bad_upload_is_rejected_with_a_reason(client):
    r = client.post("/api/art", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    assert "image type" in r.json()["detail"]


def test_deleting_something_absent_is_404(client):
    assert client.delete("/api/art/nothing-here").status_code == 404


def test_art_endpoints_are_gated_by_the_token(project: Path):
    import yaml

    cfg = project / "config" / "settings.yaml"
    data = yaml.safe_load(cfg.read_text())
    data.setdefault("server", {})["access_token"] = "tok"
    cfg.write_text(yaml.safe_dump(data))
    c = TestClient(create_app(str(cfg)))

    assert c.get("/api/art").status_code == 404
    assert c.post("/api/art", files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 404
    assert c.get("/api/art?k=tok").status_code == 200


def test_the_editor_has_an_upload_control(client):
    html = client.get("/edit").text
    assert 'id="artfile"' in html and "/api/art" in html
