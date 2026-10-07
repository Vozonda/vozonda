"""Unit tests for Podcasting 2.0 namespace features (Value4Value and WebVTT transcripts)."""

import pytest
from fastapi.testclient import TestClient

from vozonda_api.main import app, store


@pytest.fixture(autouse=True)
def _public_feed(monkeypatch):
    """These tests check feed content; feeds are private by default (L2)."""
    import vozonda_api.routers.feeds as feeds_mod

    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda: True)


@pytest.fixture
def client():
    return TestClient(app)


def test_vtt_endpoint_returns_clean_webvtt(client):
    job_id = "test-vtt-job"
    store.create(
        job_id=job_id,
        url="https://example.com/test",
        style="balanced",
        fmt="dialog",
        language="en",
        hosts=2,
    )
    store.update(
        job_id,
        title="Testing Podcasting 2.0 Transcripts",
        state="done",
        script=[
            {"speaker": 0, "name": "Alice", "text": "Welcome to the podcast.", "t0": 0.0, "t1": 2.5},
            {"speaker": 1, "name": "Bob", "text": "Glad to be here!", "t0": 2.5, "t1": 5.0},
        ],
    )

    resp = client.get(f"/vtt/{job_id}.vtt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/vtt")
    text = resp.text
    assert "WEBVTT" in text
    assert "NOTE Title: Testing Podcasting 2.0 Transcripts" in text
    assert "00:00:00.000 --> 00:00:02.500" in text
    assert "<v Alice>Welcome to the podcast." in text
    assert "<v Bob>Glad to be here!" in text


def test_srt_endpoint_returns_clean_srt(client):
    job_id = "test-srt-job"
    store.create(
        job_id=job_id,
        url="https://example.com/test-srt",
        style="balanced",
        fmt="dialog",
        language="en",
        hosts=2,
    )
    store.update(
        job_id,
        title="Testing SRT Subtitles",
        state="done",
        script=[
            {"speaker": 0, "name": "Alice", "text": "Welcome to the show.", "t0": 0.0, "t1": 2.5},
        ],
    )

    resp = client.get(f"/srt/{job_id}.srt")
    assert resp.status_code == 200
    assert "00:00:00,000 --> 00:00:02,500" in resp.text
    assert "[Alice] Welcome to the show." in resp.text


def test_feed_includes_podcasting20_transcript_and_namespace(client):
    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert 'xmlns:podcast="https://podcastindex.org/namespace/1.0"' in resp.text


def test_feed_includes_podcast_chapters_when_job_has_chapters(client):
    job_id = "test-chapters-job"
    store.create(
        job_id=job_id,
        url="https://example.com/chapters",
        style="balanced",
        fmt="dialog",
        language="en",
        hosts=2,
    )
    store.update(
        job_id,
        title="Testing Podcasting 2.0 Chapters",
        state="done",
        script=[
            {"speaker": 0, "name": "Alice", "text": "Welcome to the podcast.", "t0": 0.0, "t1": 2.5},
            {"speaker": 1, "name": "Bob", "text": "Glad to be here!", "t0": 2.5, "t1": 5.0},
        ],
        chapters=[
            {"index": 0, "title": "Introduction", "url": "https://example.com/intro", "word_offset": 0},
            {"index": 1, "title": "Main Topic", "url": "https://example.com/main", "word_offset": 5},
        ],
    )

    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert '<podcast:chapters>' in resp.text
    assert '<podcast:chapter index="0"' in resp.text
    assert '<podcast:chapter index="1"' in resp.text
    assert 'start="00:00:00.000"' in resp.text
    assert 'title="Introduction"' in resp.text
    assert 'title="Main Topic"' in resp.text
    assert '</podcast:chapters>' in resp.text


def test_feed_etag_caching(client):
    resp1 = client.get("/feed.xml")
    assert resp1.status_code == 200
    etag = resp1.headers.get("etag")
    assert etag is not None

    resp2 = client.get("/feed.xml", headers={"if-none-match": etag})
    assert resp2.status_code == 304
    assert resp2.headers.get("etag") == etag


def test_feed_etag_changes_when_content_changes(client):
    job_id = "etag-job"
    store.create(
        job_id=job_id,
        url="https://example.com/etag",
        style="balanced",
        fmt="dialog",
        language="en",
        hosts=2,
    )
    store.update(job_id, title="ETag Test", state="done")

    resp1 = client.get("/feed.xml")
    etag1 = resp1.headers.get("etag")
    assert etag1 is not None

    store.update(job_id, title="ETag Test Updated", state="done")
    resp2 = client.get("/feed.xml")
    etag2 = resp2.headers.get("etag")
    assert etag2 is not None
    assert etag1 != etag2


def test_feed_etag_changes_when_the_channel_changes(client):
    """The ETag must not be derived from items alone: a renamed show is new content."""
    from vozonda_api import settings_store

    before = settings_store.get_setting("show.name") or ""
    etag = client.get("/feed.xml").headers["etag"]
    try:
        settings_store.set_setting("show.name", "Renamed Show For ETag Test")
        resp = client.get("/feed.xml", headers={"if-none-match": etag})
        assert resp.status_code == 200
        assert resp.headers["etag"] != etag
    finally:
        settings_store.set_setting("show.name", before)
