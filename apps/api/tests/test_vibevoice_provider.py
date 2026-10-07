"""Tests for the VibeVoice TTS engine provider."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vozonda_api.plugins.types import Permission
from vozonda_api.providers import tts_engines
from vozonda_api.providers.vibevoice import META, is_installed
from vozonda_api.render_vibevoice import build_conversation


def test_meta_fields():
    assert META.id == "vibevoice"
    assert META.kind.name == "TTS_ENGINE"
    assert "vibevoice" in META.label.lower()
    assert META.renderer == "render_vibevoice.py"
    assert META.license == "MIT"
    assert META.commercial_use is True
    assert META.ui_badge == "local GPU"
    assert "VOZONDA_VIBEVOICE_PY" in META.ui_fix_hint
    assert "transformers>=5.17" in META.ui_fix_hint
    assert Permission.SUBPROCESS in META.permissions
    assert Permission.GPU in META.permissions


def test_is_installed_false_when_missing(monkeypatch):
    import vozonda_api.providers.vibevoice as vv

    with patch.object(vv, "RENDER_PY", Path("/nonexistent/python")), \
         patch.object(vv, "VOICES_DIR", Path("/nonexistent/voices")):
        assert is_installed() is False


def test_build_conversation_first_turns_have_samples(tmp_path):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "en-Frank_man.wav").write_bytes(b"RIFF....WAVEfmt ")
    (voices_dir / "en-Maya_woman.wav").write_bytes(b"RIFF....WAVEfmt ")

    segments = [
        {"speaker": "A", "text": "Hello world"},
        {"speaker": "B", "text": "Hi there"},
        {"speaker": "A", "text": "How are you?"},
        {"speaker": "B", "text": "Good thanks"},
    ]
    voices = {
        "A": {"timbre": "en-Frank_man.wav"},
        "B": {"timbre": "en-Maya_woman.wav"},
    }

    conversations = build_conversation(segments, voices, voices_dir)
    assert len(conversations) == 1
    conv = conversations[0]
    assert len(conv) == 4

    # First turn for A (role '0') has audio sample
    assert conv[0]["role"] == "0"
    assert conv[0].get("type") == "audio"
    assert conv[0].get("url") == str(voices_dir / "en-Frank_man.wav")

    # Second turn for B (role '1') has audio sample
    assert conv[1]["role"] == "1"
    assert conv[1].get("type") == "audio"
    assert conv[1].get("url") == str(voices_dir / "en-Maya_woman.wav")

    # Subsequent turns for same speakers do NOT have audio sample
    assert "type" not in conv[2]
    assert "type" not in conv[3]


def test_build_conversation_rejects_five_speakers(tmp_path):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    for name in ("a.wav", "b.wav", "c.wav", "d.wav", "e.wav"):
        (voices_dir / name).write_bytes(b"RIFF....WAVEfmt ")

    segments = [
        {"speaker": "A", "text": "1"},
        {"speaker": "B", "text": "2"},
        {"speaker": "C", "text": "3"},
        {"speaker": "D", "text": "4"},
        {"speaker": "E", "text": "5"},
    ]
    voices = {
        "A": {"timbre": "a.wav"},
        "B": {"timbre": "b.wav"},
        "C": {"timbre": "c.wav"},
        "D": {"timbre": "d.wav"},
        "E": {"timbre": "e.wav"},
    }

    with pytest.raises(ValueError, match="at most 4 speakers"):
        build_conversation(segments, voices, voices_dir)


def test_vibevoice_in_tts_engines():
    engines = tts_engines(refresh=True)
    assert "vibevoice" in engines
    assert engines["vibevoice"].id == "vibevoice"
    assert engines["vibevoice"].renderer == "render_vibevoice.py"

def test_voice_ids_resolve_to_the_demo_sample_files(tmp_path):
    from vozonda_api.render_vibevoice import resolve_sample

    for name in ("en-Frank_man.wav", "en-Maya_woman.wav"):
        (tmp_path / name).write_bytes(b"RIFF")
    assert resolve_sample(tmp_path, "frank").name == "en-Frank_man.wav"
    assert resolve_sample(tmp_path, "Maya").name == "en-Maya_woman.wav"
    assert resolve_sample(tmp_path, "en-Frank_man.wav").name == "en-Frank_man.wav"
    assert resolve_sample(tmp_path, "nobody") is None
    assert resolve_sample(tmp_path, "../etc/passwd") is None
