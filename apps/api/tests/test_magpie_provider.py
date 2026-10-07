"""Magpie TTS Multilingual (NVIDIA NIM, hosted) as a cloud voice engine.

Tested by hand on 2026-09-25: EN and DE via grpc.nvcf.nvidia.com, ~5 s of
audio per 0.5 s. No network here: the renderer's synth call is replaced.
The hosted API runs on NVIDIA's trial terms (testing only), so the engine
is marked non-commercial and billing blocks it.
"""

import importlib
import json
import sys

import pytest

from vozonda_api.plugins.types import Permission, PluginKind
from vozonda_api.providers import magpie, tts_engines
from vozonda_api.voices import default_cast_for, speakers_for

RENDER = "vozonda_api.render_magpie"


def _render():
    sys.modules.pop(RENDER, None)
    return importlib.import_module(RENDER)


def test_meta_is_a_cloud_engine_without_commercial_use():
    meta = magpie.META
    assert meta.id == "magpie" and meta.kind == PluginKind.TTS_ENGINE
    assert meta.renderer == "render_magpie.py"
    assert Permission.NETWORK in meta.permissions
    assert meta.commercial_use is False
    assert "magpie" in tts_engines(refresh=True)


def test_voices_carry_their_language_and_cast_per_language():
    ids = {s["id"] for s in speakers_for("magpie")}
    assert {"en_aria", "en_jason", "de_mia", "de_leo", "fr_louise"} <= ids
    cast = default_cast_for("magpie")
    assert cast["de"]["a"].startswith("de_") and cast["de"]["b"].startswith("de_")
    assert cast["en"]["a"].startswith("en_") and cast["en"]["a"] != cast["en"]["b"]


def test_voice_name_and_language_code_come_from_the_voice_id():
    r = _render()
    assert r.voice_for("de_mia") == ("Magpie-Multilingual.DE-DE.Mia", "de-DE")
    assert r.voice_for("en_jason") == ("Magpie-Multilingual.EN-US.Jason", "en-US")
    assert r.voice_for("nobody") == ("Magpie-Multilingual.EN-US.Aria", "en-US")


def test_long_turns_are_split_at_sentence_ends():
    r = _render()
    text = " ".join(f"Sentence number {i} has a few words in it." for i in range(40))
    parts = r.chunks(text, max_chars=300)
    assert all(len(p) <= 300 for p in parts)
    assert " ".join(parts) == text


def test_render_writes_audio_timing_and_retries_rate_limits(tmp_path, monkeypatch):
    r = _render()
    calls = []

    class RateLimited(Exception):
        code = "RESOURCE_EXHAUSTED"

    def fake_synth(text, voice, lang):
        calls.append((text, voice, lang))
        if len(calls) == 1:
            raise RateLimited()
        return b"\x00\x10" * 4410  # 0.1 s at 44.1 kHz, 16 bit

    monkeypatch.setattr(r, "_sleep", lambda s: None)
    cfg = {"segments": [{"speaker": "A", "text": "Hello there."}, {"speaker": "B", "text": "Hallo."}],
           "voices": {"A": {"timbre": "en_aria"}, "B": {"timbre": "de_mia"}},
           "gap_ms": 100, "out": str(tmp_path / "ep.wav")}
    r.render(cfg, fake_synth)
    assert [c[1:] for c in calls] == [("Magpie-Multilingual.EN-US.Aria", "en-US")] * 2 + \
        [("Magpie-Multilingual.DE-DE.Mia", "de-DE")]
    assert (tmp_path / "ep.wav").stat().st_size > 44
    timing = json.loads((tmp_path / "ep.timing.json").read_text())
    assert timing == [pytest.approx(0.2, abs=0.01)] * 2


def test_missing_key_or_client_means_not_installed(monkeypatch):
    monkeypatch.setattr(magpie, "_client_available", lambda: True)
    monkeypatch.setattr(magpie, "nim_api_key", lambda: "")
    assert magpie.is_installed() is False
    monkeypatch.setattr(magpie, "nim_api_key", lambda: "k")
    assert magpie.is_installed() is True
    monkeypatch.setattr(magpie, "_client_available", lambda: False)
    assert magpie.is_installed() is False
