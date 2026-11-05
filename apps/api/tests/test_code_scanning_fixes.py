"""Code-scanning triage 2026-11: one test per alert group that turned out to be real."""

import asyncio
import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main, music_store
from vozonda_api.nostr_zaps import parse_lightning_address
from vozonda_api.settings_store import _validate

EVIL_BASE = 'http://x"><img src=x onerror=alert(1)>'
DONE_JOB = {
    "state": "done",
    "title": "t",
    "script": [{"speaker": "a", "text": "hello there world"}],
    "stages": [],
}


@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    root = tmp_path / "media"
    root.mkdir()
    monkeypatch.setattr(main, "MEDIA_DIR", root)
    return root


def test_share_clip_escapes_the_clip_id(media):
    clip_id = 'x"><img src=x onerror=alert(1)>'
    (media / f"{clip_id}.mp3").write_bytes(b"id3")
    r = TestClient(main.app).get(f"/share/{quote(clip_id)}")
    assert r.status_code == 200
    assert "<img src=x" not in r.text


def test_share_page_escapes_the_base_url(media, monkeypatch):
    monkeypatch.setattr(main.store, "get", lambda _id: dict(DONE_JOB))
    monkeypatch.setattr(main, "public_base", lambda _r: EVIL_BASE)
    r = TestClient(main.app).get("/e/job1")
    assert r.status_code == 200
    assert "<img src=x" not in r.text


def test_clip_page_escapes_the_base_url(media, monkeypatch):
    monkeypatch.setattr(main.store, "get", lambda _id: dict(DONE_JOB))
    monkeypatch.setattr(main, "public_base", lambda _r: EVIL_BASE)
    clip = media / "job1-clip-0-0.mp3"
    clip.write_bytes(b"id3")
    monkeypatch.setattr(main, "find_clip_file", lambda *_a: clip)
    r = TestClient(main.app).get("/e/job1/clip/0-0")
    assert r.status_code == 200
    assert "<img src=x" not in r.text


def test_image_route_does_not_reveal_files_outside_media(media):
    (media.parent / "exists.txt").write_text("x")
    client = TestClient(main.app)
    present = client.get("/img/..%2Fexists.txt")
    missing = client.get("/img/..%2Fmissing.txt")
    assert present.status_code == missing.status_code


def test_peaks_upload_stays_inside_media(media):
    class Body:
        async def json(self):
            return {"peaks": [0.1]}

    with pytest.raises(main.HTTPException):
        asyncio.run(main.put_audio_peaks("../evil", Body()))
    assert not (media.parent / "evil.peaks.json").exists()


def test_cover_upload_for_unknown_watchlist_leaves_no_file(media, monkeypatch):
    def no_such_list(_wid):
        raise KeyError(_wid)

    monkeypatch.setattr("vozonda_api.watchlist.get_watchlist", no_such_list)
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    r = TestClient(main.app).post("/watchlist/nope/cover", files={"file": ("c.png", png, "image/png")})
    assert r.status_code == 404
    assert list(media.iterdir()) == []


def test_cover_upload_stores_a_png(media, monkeypatch):
    saved = {}
    monkeypatch.setattr("vozonda_api.watchlist.get_watchlist", lambda _wid: {"id": _wid})
    monkeypatch.setattr("vozonda_api.watchlist.update_watchlist", lambda _wid, **kw: saved.update(kw))
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    r = TestClient(main.app).post("/watchlist/w1/cover", files={"file": ("c.png", png, "image/png")})
    assert r.status_code == 200
    assert (media / saved["cover_image"]).read_bytes() == png


def test_cover_upload_rejects_other_files(media, monkeypatch):
    monkeypatch.setattr("vozonda_api.watchlist.get_watchlist", lambda _wid: {"id": _wid})
    r = TestClient(main.app).post("/watchlist/w1/cover", files={"file": ("c.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422


def test_music_reset_rejects_a_path_as_kind(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    victim = tmp_path / "victim.mp3"
    victim.write_bytes(b"keep")
    monkeypatch.setattr(music_store, "get_music_dir", lambda: music)
    with pytest.raises(ValueError):
        music_store.reset_music("../victim")
    assert victim.exists()


def test_music_reset_endpoint_answers_422_for_a_bad_kind(tmp_path, monkeypatch):
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.setattr(music_store, "get_music_dir", lambda: tmp_path)
    r = TestClient(main.app).post("/music/reset", content=json.dumps({"kind": "../victim"}))
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://api.anthropic.com/v1", True),
        ("https://API.anthropic.com", True),
        ("https://api.anthropic.com.evil.example/v1", False),
        ("https://evil.example/api.anthropic.com", False),
        ("http://127.0.0.1:30001/v1", False),
    ],
)
def test_anthropic_base_compares_the_host(base, expected):
    from vozonda_api.providers.script import is_anthropic_base

    assert is_anthropic_base(base) is expected


def test_lightning_address_has_a_length_limit():
    with pytest.raises(ValueError):
        parse_lightning_address("a" * 400 + "@example.com")


def test_model_id_has_a_length_limit():
    with pytest.raises(ValueError):
        _validate("llm.nim_model", "v/" + "a" * 400)
