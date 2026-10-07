"""Tests for AI-generated disclosure feature (VOZONDA-L1)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from vozonda_api.pipeline import _build_master_ffmpeg_args
from vozonda_api.settings_store import SETTING_KEYS

_DISCLOSURE_LINE = "AI-generated: script by qwen3.6-35b, voices by qwen_tts."

_STAGES_JSON = json.dumps([
    {"name": "script", "meta": {"llm_model": "qwen3.6-35b", "llm_provider": "qwen_vllm"}},
    {"name": "voice", "meta": {"engine": "qwen_tts"}},
])


def _feed_row() -> dict:
    return {
        "id": "test-job-1",
        "title": "Test Episode",
        "url": "https://example.com/article",
        "description": "A test episode",
        "style": "balanced",
        "format": "dialog",
        "script": json.dumps([{"speaker": "A", "text": "Hello"}]),
        "stages": _STAGES_JSON,
        "created_at": 1700000000,
        "duration_ms": 120000,
        "explicit": False,
        "chapters": "[]",
        "digest_sources": None,
        "show_name": "Test Show",
    }


def _job_dict() -> dict:
    return {
        "id": "test-job-1",
        "title": "Test Episode",
        "state": "done",
        "url": "https://example.com/article",
        "script": [{"speaker": "A", "text": "Hello"}],
        "stages": json.loads(_STAGES_JSON),
        "created_at": 1700000000,
        "duration_ms": 120000,
        "show_name": "Test Show",
        "show_author": "Test Author",
        "language": "en",
        "og_image": None,
        "digest_sources": None,
    }


def _get_setting_stub(disclosure: str):
    def _stub(key: str):
        if key == "disclosure.ai_label":
            return disclosure
        if key == "feed.public":
            return "1"
        return None

    return _stub


def _mock_connect(rows: list[dict]) -> MagicMock:
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    ctx = MagicMock()
    ctx.__enter__.return_value = mock_conn
    ctx.__exit__.return_value = False
    return ctx


def test_disclosure_setting_exists():
    assert "disclosure.ai_label" in SETTING_KEYS


def test_disclosure_setting_validated():
    import pytest

    from vozonda_api.settings_store import set_setting

    with pytest.raises(ValueError):
        set_setting("disclosure.ai_label", "yes")


def test_disclosure_setting_default():
    from vozonda_api.main import app

    client = TestClient(app)
    res = client.get("/settings")
    assert res.status_code == 200
    assert res.json()["defaults"]["disclosure.ai_label"] == "1"


def test_build_master_ffmpeg_args_without_metadata():
    wav = Path("/tmp/test.wav")
    mp3 = Path("/tmp/test.mp3")
    args = _build_master_ffmpeg_args(wav, mp3, speed=1.0)
    expected = [
        "ffmpeg", "-y", "-i", str(wav),
        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
        "-b:a", "128k",
        str(mp3),
    ]
    assert args == expected


def test_build_master_ffmpeg_args_with_metadata():
    wav = Path("/tmp/test.wav")
    mp3 = Path("/tmp/test.mp3")
    metadata = {
        "comment": _DISCLOSURE_LINE,
        "AI_GENERATED": "true",
    }
    args = _build_master_ffmpeg_args(wav, mp3, speed=1.0, metadata=metadata)
    assert "-metadata" in args
    assert f"comment={_DISCLOSURE_LINE}" in args
    assert "AI_GENERATED=true" in args
    assert args.index("-metadata") < args.index(str(mp3))


def test_build_master_ffmpeg_args_with_speed():
    wav = Path("/tmp/test.wav")
    mp3 = Path("/tmp/test.mp3")
    args = _build_master_ffmpeg_args(wav, mp3, speed=1.5)
    assert any("atempo=1.5" in a for a in args)


def test_feed_contains_disclosure_when_enabled():
    import vozonda_api.main as main_module

    client = TestClient(main_module.app)
    with (
        patch("sqlite3.connect", return_value=_mock_connect([_feed_row()])),
        patch("vozonda_api.settings_store.get_setting", side_effect=_get_setting_stub("1")),
        patch("vozonda_api.routers.feeds.get_setting", side_effect=_get_setting_stub("1")),
        patch.object(main_module, "get_setting", side_effect=_get_setting_stub("1")),
    ):
        response = client.get("/feed.xml")
    assert response.status_code == 200
    assert _DISCLOSURE_LINE in response.text


def test_feed_no_disclosure_when_disabled():
    import vozonda_api.main as main_module

    client = TestClient(main_module.app)
    with (
        patch("sqlite3.connect", return_value=_mock_connect([_feed_row()])),
        patch("vozonda_api.settings_store.get_setting", side_effect=_get_setting_stub("0")),
        patch("vozonda_api.routers.feeds.get_setting", side_effect=_get_setting_stub("0")),
        patch.object(main_module, "get_setting", side_effect=_get_setting_stub("0")),
    ):
        response = client.get("/feed.xml")
    assert response.status_code == 200
    assert "AI-generated:" not in response.text


def test_episode_page_contains_disclosure_when_enabled():
    import vozonda_api.main as main_module

    mock_store = MagicMock()
    mock_store.get.return_value = _job_dict()

    client = TestClient(main_module.app)
    with (
        patch.object(main_module, "store", mock_store),
        patch("vozonda_api.settings_store.get_setting", side_effect=_get_setting_stub("1")),
    ):
        response = client.get("/e/test-job-1")
    assert response.status_code == 200
    assert _DISCLOSURE_LINE in response.text


def test_episode_page_no_disclosure_when_disabled():
    import vozonda_api.main as main_module

    mock_store = MagicMock()
    mock_store.get.return_value = _job_dict()

    client = TestClient(main_module.app)
    with (
        patch.object(main_module, "store", mock_store),
        patch("vozonda_api.settings_store.get_setting", side_effect=_get_setting_stub("0")),
    ):
        response = client.get("/e/test-job-1")
    assert response.status_code == 200
    assert "AI-generated:" not in response.text


def test_hierarchical_feed_contains_disclosure_when_enabled():
    import vozonda_api.main as main_module

    client = TestClient(main_module.app)
    with (
        patch("sqlite3.connect", return_value=_mock_connect([_feed_row()])),
        patch("vozonda_api.settings_store.get_setting", side_effect=_get_setting_stub("1")),
        patch("vozonda_api.routers.feeds.get_setting", side_effect=_get_setting_stub("1")),
        patch.object(main_module, "get_setting", side_effect=_get_setting_stub("1")),
    ):
        response = client.get("/creator/test-show/feed.xml")
    assert response.status_code == 200
    assert _DISCLOSURE_LINE in response.text


def test_hierarchical_feed_no_disclosure_when_disabled():
    import vozonda_api.main as main_module

    client = TestClient(main_module.app)
    with (
        patch("sqlite3.connect", return_value=_mock_connect([_feed_row()])),
        patch("vozonda_api.settings_store.get_setting", side_effect=_get_setting_stub("0")),
        patch("vozonda_api.routers.feeds.get_setting", side_effect=_get_setting_stub("0")),
        patch.object(main_module, "get_setting", side_effect=_get_setting_stub("0")),
    ):
        response = client.get("/creator/test-show/feed.xml")
    assert response.status_code == 200
    assert "AI-generated:" not in response.text


def test_disclosure_is_on_when_never_set(tmp_path, monkeypatch):
    """Settings page showed 'enabled' (default '1') while the backend compared an unset value
    (None) with '1' and wrote no AI_GENERATED tag. Unset must mean on; '0' still turns it off."""
    import vozonda_api.jobs as jobs_mod
    from vozonda_api import settings_store as ss

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    jobs_mod.init_db()
    assert ss.get_setting("disclosure.ai_label") == "1"
    ss.set_setting("disclosure.ai_label", "0")
    assert ss.get_setting("disclosure.ai_label") == "0"
