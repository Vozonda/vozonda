"""Tests for the Dia (Nari Labs 1.6B) TTS engine provider."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vozonda_api.plugins.types import Permission
from vozonda_api.providers import tts_engines
from vozonda_api.providers.dia import META, is_installed
from vozonda_api.render_dia import (
    chunk_dialogue,
    resolve_sample,
    to_dia_text,
)


def test_meta_fields():
    """Verify PluginMeta has the expected fields."""
    assert META.id == "dia"
    assert META.kind.name == "TTS_ENGINE"
    assert "dia" in META.label.lower()
    assert META.renderer == "render_dia.py"
    assert META.license == "Apache-2.0"
    assert META.commercial_use is True
    assert META.ui_badge == "local GPU"
    assert "VOZONDA_DIA_PY" in META.ui_fix_hint
    assert Permission.SUBPROCESS in META.permissions
    assert Permission.GPU in META.permissions


def test_is_installed_false_when_missing(monkeypatch):
    """is_installed returns False when paths don't exist."""
    from vozonda_api.providers import dia

    with patch.object(dia, "RENDER_PY", Path("/nonexistent/python")), \
         patch.object(dia, "VOICES_DIR", Path("/nonexistent/voices")):
        assert is_installed() is False


def test_to_dia_text_keeps_supported_tags():
    """Supported nonverbal tags are preserved."""
    text = "Hello (laughs) world (sighs) here"
    result = to_dia_text(text)
    assert "(laughs)" in result
    assert "(sighs)" in result


def test_to_dia_text_strips_unsupported_tags():
    """Unsupported bracketed expressions are removed."""
    text = "Hello [unknown] world (not_supported) here"
    result = to_dia_text(text)
    assert "[unknown]" not in result
    assert "(not_supported)" not in result
    assert result == "Hello world here"


def test_to_dia_text_strips_mixed_brackets():
    """All bracket types are stripped when not in the supported list."""
    text = "Hello (unlisted) [stuff] there"
    result = to_dia_text(text)
    assert "(unlisted)" not in result
    assert "[stuff]" not in result
    assert result == "Hello there"


def test_to_dia_text_only_supported():
    """Only supported nonverbal tags remain."""
    text = "(laughs) Hello (sighs) world (coughs)"
    result = to_dia_text(text)
    assert result == "(laughs) Hello (sighs) world (coughs)"


def test_chunk_dialogue_keeps_turns():
    """Turns are not split across chunks."""
    turns = [
        {"speaker": "A", "text": "First turn text."},
        {"speaker": "B", "text": "Second turn text."},
    ]
    chunks = chunk_dialogue(turns)
    assert len(chunks) >= 1
    combined = " ".join(chunks)
    assert "First turn text" in combined
    assert "Second turn text" in combined


def test_chunk_dialogue_two_speakers_alternates():
    """Speakers alternate correctly in dia format."""
    turns = [
        {"speaker": "A", "text": "Hello world."},
        {"speaker": "B", "text": "Hi there."},
        {"speaker": "A", "text": "How are you?"},
    ]
    chunks = chunk_dialogue(turns)
    combined = " ".join(chunks)
    # Should have S1 and S2 tags
    assert "[S1]" in combined
    assert "[S2]" in combined
    # First turn (A->S1) should come before second (B->S2)
    s1_first = combined.index("[S1]")
    s2_first = combined.index("[S2]")
    assert s1_first < s2_first


def test_chunk_dialogue_rejects_three_speakers():
    """Three speakers raises ValueError."""
    turns = [
        {"speaker": "A", "text": "Hello."},
        {"speaker": "B", "text": "Hi."},
        {"speaker": "C", "text": "Hey."},
    ]
    with pytest.raises(ValueError, match="exactly 2 speakers"):
        chunk_dialogue(turns)


def test_resolve_sample_inside_voices_dir(tmp_path: Path):
    """Samples inside voices_dir resolve correctly."""
    (tmp_path / "s1.wav").write_bytes(b"RIFF....WAVEfmt ")
    sample = resolve_sample(tmp_path, "s1")
    assert sample is not None
    assert sample.name == "s1.wav"


def test_resolve_sample_outside_voices_dir_raises(tmp_path: Path):
    """Sample path outside voices_dir raises ValueError."""
    # voices_dir is a subdirectory; the target file is at tmp_path level
    (tmp_path / "evil.wav").write_bytes(b"RIFF....WAVEfmt ")
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    # Access via relative path that escapes the subdirectory
    with pytest.raises(ValueError, match="escapes"):
        resolve_sample(voices_dir, "../evil.wav")


def test_resolve_sample_returns_none_when_missing(tmp_path: Path):
    """Returns None when no sample matches."""
    sample = resolve_sample(tmp_path, "nonexistent")
    assert sample is None


def test_dia_in_tts_engines():
    """'dia' appears in tts_engines()."""
    engines = tts_engines(refresh=True)
    assert "dia" in engines
    assert engines["dia"].id == "dia"
    assert engines["dia"].renderer == "render_dia.py"

def test_renderer_accepts_the_language_name_the_pipeline_passes(tmp_path: Path):
    """The pipeline sends display names ('English'); the landed renderer only
    accepted 'en' and refused every real render before loading the model."""
    import subprocess

    pytest.importorskip("torch")  # the renderer imports torch before the language check
    import sys

    script = Path(__file__).resolve().parents[1] / "src" / "vozonda_api" / "render_dia.py"
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"segments": [], "language": "English", "out": str(tmp_path / "o.wav")}))
    # No segments: the run stops with "no audio produced" before any model
    # load, but only after the language check has passed.
    out = subprocess.run([sys.executable, str(script), "--config", str(cfg)], capture_output=True, text=True, check=False,
                         timeout=120)
    assert "English only" not in out.stderr, out.stderr
    assert "no audio produced" in out.stderr, out.stderr
