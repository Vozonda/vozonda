"""Piper voices in the docker CPU quickstart (2026-09-25).

A clean-clone docker run failed at the voice stage: piper-tts 1.8 does not
download voices by itself, 6 of 14 model names did not exist on the Piper voice
list, and English episodes were cast with German voices (thorsten + kerstin)
because every language got the same cast.
"""

import json
import subprocess
import sys
from pathlib import Path

from vozonda_api import render_piper
from vozonda_api.voices import PIPER_SPEAKERS, default_cast_for

# Model names published at huggingface.co/rhasspy/piper-voices (voices.json, 2026-09-25)
PUBLISHED = {
    "de_DE-thorsten-medium", "de_DE-kerstin-low", "de_DE-ramona-low",
    "en_GB-alan-medium", "en_GB-cori-medium", "en_US-ryan-medium", "en_US-amy-medium",
    "fr_FR-siwis-medium", "fr_FR-gilles-low", "es_ES-carlfm-x_low",
    "es_ES-davefx-medium", "it_IT-riccardo-x_low", "it_IT-paola-medium",
}
NATIVE = {"de": "German", "en": "English", "fr": "French", "es": "Spanish", "it": "Italian"}


def test_every_piper_voice_maps_to_a_published_model():
    ids = {s["id"] for s in PIPER_SPEAKERS}
    assert ids == set(render_piper.VOICE_MODELS)
    assert set(render_piper.VOICE_MODELS.values()) <= PUBLISHED


def test_piper_cast_speaks_the_episode_language():
    native = {s["id"]: s["native"] for s in PIPER_SPEAKERS}
    cast = default_cast_for("piper")
    for lang, name in NATIVE.items():
        for role in ("a", "b", "solo"):
            assert native[cast[lang][role]].startswith(name), (lang, role, cast[lang])
        assert cast[lang]["a"] != cast[lang]["b"], (lang, cast[lang])


def test_missing_model_is_downloaded_into_the_data_dir(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "piper.download_voices" in cmd:
            (tmp_path / "en_US-ryan-medium.onnx").write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(render_piper.subprocess, "run", fake_run)
    model = render_piper.ensure_model("en_US-ryan-medium", tmp_path)
    assert model == tmp_path / "en_US-ryan-medium.onnx"
    assert calls == [[sys.executable, "-m", "piper.download_voices", "--download-dir", str(tmp_path),
                      "en_US-ryan-medium"]]
    # second call: already there, no download
    assert render_piper.ensure_model("en_US-ryan-medium", tmp_path) == model
    assert len(calls) == 1


def test_failed_download_names_the_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(render_piper.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"HTTP 404"))
    try:
        render_piper.ensure_model("en_US-nobody-medium", tmp_path)
    except RuntimeError as exc:
        assert "en_US-nobody-medium" in str(exc) and "HTTP 404" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_data_dir_follows_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZONDA_PIPER_DIR", str(tmp_path))
    assert render_piper.data_dir() == tmp_path
    monkeypatch.delenv("VOZONDA_PIPER_DIR")
    assert render_piper.data_dir() == Path.home() / ".local/share/piper"


def test_render_config_is_json_roundtrip_safe():
    # guard: the renderer module must stay importable without piper installed
    assert json.loads(json.dumps(render_piper.VOICE_MODELS))
