"""Tests for the Higgs Audio v2 provider: META, install probe, pure
preparation functions, sample path guard, registry discovery.

No model, GPU or network: the engine package is never imported here.
"""

import importlib
import sys

import pytest

from vozonda_api.plugins.types import PluginKind
from vozonda_api.providers import higgs, tts_engines

RENDER = "vozonda_api.render_higgs"


def _render():
    """Import the renderer as a plain module with heavy deps blocked."""
    sys.modules.pop(RENDER, None)
    return importlib.import_module(RENDER)


def test_meta_fields():
    meta = higgs.META
    assert meta.id == "higgs"
    assert meta.kind == PluginKind.TTS_ENGINE
    assert meta.renderer == "render_higgs.py"
    assert meta.license == "Apache-2.0"
    assert meta.commercial_use is False


def test_is_installed_false_when_render_py_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(higgs, "RENDER_PY", str(tmp_path / "nope" / "python"))
    assert higgs.is_installed() is False


def test_is_installed_true_when_render_py_exists(monkeypatch, tmp_path):
    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(higgs, "RENDER_PY", str(fake))
    assert higgs.is_installed() is True


def test_build_transcript_maps_speakers_in_order():
    r = _render()
    turns = [
        {"speaker": "B", "text": "first"},
        {"speaker": "A", "text": "second"},
        {"speaker": "B", "text": "third"},
    ]
    out = r.build_transcript(turns)
    assert out == "[SPEAKER0] first\n[SPEAKER1] second\n[SPEAKER0] third"


def test_build_transcript_skips_empty_text():
    r = _render()
    turns = [
        {"speaker": "A", "text": "  "},
        {"speaker": "B", "text": "hello"},
    ]
    assert r.build_transcript(turns) == "[SPEAKER0] hello"


def test_build_transcript_rejects_more_than_four_speakers():
    r = _render()
    turns = [{"speaker": s, "text": "hi"} for s in ("A", "B", "C", "D", "E")]
    with pytest.raises(ValueError):
        r.build_transcript(turns)


def test_build_system_prompt_scene_format():
    r = _render()
    prompt = r.build_system_prompt(language="German", tone="calm")
    assert prompt.startswith("Generate audio following instruction.")
    assert "<|scene_desc_start|>" in prompt
    assert "<|scene_desc_end|>" in prompt
    assert "German" in prompt
    assert "calm" in prompt


def test_chunk_turns_respects_word_budget():
    r = _render()
    turns = [{"speaker": "A", "text": " ".join(["w"] * 60)} for _ in range(5)]
    chunks = r.chunk_turns(turns, max_words=150)
    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [2, 2, 1]
    # order preserved: flattened chunks equal the input
    assert [t for c in chunks for t in c] == turns


def test_chunk_turns_single_long_turn_gets_own_chunk():
    r = _render()
    turns = [{"speaker": "A", "text": " ".join(["w"] * 300)}]
    chunks = r.chunk_turns(turns, max_words=150)
    assert chunks == [turns]


def test_resolve_sample_inside_voices_dir(tmp_path):
    r = _render()
    (tmp_path / "belinda.wav").write_bytes(b"RIFF")
    p = r.resolve_sample("belinda.wav", voices_dir=tmp_path)
    assert p == (tmp_path / "belinda.wav").resolve()


def test_resolve_sample_outside_voices_dir_rejected(tmp_path):
    r = _render()
    with pytest.raises(ValueError):
        r.resolve_sample("../outside.wav", voices_dir=tmp_path / "voices")
    with pytest.raises(ValueError):
        r.resolve_sample("/etc/passwd", voices_dir=tmp_path)


def test_higgs_discovered_in_tts_engines():
    metas = tts_engines(refresh=True)
    assert "higgs" in metas
    assert metas["higgs"].renderer == "render_higgs.py"
