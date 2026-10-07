"""Tests for safe music asset storage and URL-only ingestion (DUE-093)."""

import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
import numpy as np
import soundfile as sf

from vozonda_api.main import app
from vozonda_api.music_store import get_music_dir, reset_music


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_music_dir():
    """Ensure media/music is cleaned up before and after each test."""
    reset_music(kind="all")
    yield
    reset_music(kind="all")


def test_music_status_default(client):
    resp = client.get("/music/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "intro" in data
    assert "outro" in data
    assert data["intro"]["mode"] == "procedural"
    assert data["outro"]["mode"] == "procedural"
    assert "jazz" in data["procedural_palette"].lower()


def test_import_music_validation(client):
    # Empty body
    resp = client.post("/music/import-url", json={})
    assert resp.status_code == 400
    assert "Missing required 'url'" in resp.json()["detail"]

    # Invalid kind
    resp = client.post("/music/import-url", json={"url": "https://example.com/audio.mp3", "kind": "invalid"})
    assert resp.status_code == 400
    assert "must be 'intro' or 'outro'" in resp.json()["detail"]


def test_import_music_ssrf_blocked(client):
    # Localhost loopback
    resp = client.post("/music/import-url", json={"url": "http://127.0.0.1:8787/test.mp3", "kind": "intro"})
    assert resp.status_code == 400
    assert "refusing to fetch local address" in resp.json()["detail"]

    # 10.x.x.x private network
    resp = client.post("/music/import-url", json={"url": "http://10.0.0.1/audio.mp3", "kind": "outro"})
    assert resp.status_code == 400
    assert "refusing to fetch local address" in resp.json()["detail"]


def test_import_music_successful_transcode(client, tmp_path):
    # Create valid synthetic wav audio
    sr = 24000
    dur = 2.0
    sig = (0.5 * np.sin(2 * np.pi * 440 * np.linspace(0, dur, int(sr * dur)))).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, sig, sr, format="WAV")
    audio_bytes = buf.getvalue()

    async def mock_aiter(*args, **kwargs):
        yield audio_bytes

    class MockStreamResponse:
        status_code = 200
        aiter_bytes = mock_aiter

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            return MockStreamResponse()

    with patch("vozonda_api.music_store.guard_url", return_value=None):
        with patch("vozonda_api.music_store.httpx.AsyncClient", return_value=MockAsyncClient()):
            resp = client.post("/music/import-url", json={"url": "https://example.com/signature_intro.wav", "kind": "intro"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["kind"] == "intro"
            assert data["filename"] == "intro.mp3"
            assert data["duration"] > 1.5

            # Verify status now reflects custom
            status_resp = client.get("/music/status")
            assert status_resp.status_code == 200
            st = status_resp.json()
            assert st["intro"]["active"] is True
            assert st["intro"]["mode"] == "custom"
            assert st["intro"]["url"] == "/music/intro.mp3"

            # Verify preview endpoint serves the custom file
            prev = client.get("/music/intro.mp3")
            assert prev.status_code == 200
            assert prev.headers["content-type"] == "audio/mpeg"

            # Reset back to built-in
            reset_resp = client.post("/music/reset", json={"kind": "intro"})
            assert reset_resp.status_code == 200
            assert "intro.mp3" in reset_resp.json()["removed"]

            # Status should be procedural again
            status_resp2 = client.get("/music/status")
            assert status_resp2.json()["intro"]["mode"] == "procedural"
