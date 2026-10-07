"""Chatterbox provider: META, install probe, pure renderer helpers, discovery.

No model, GPU or network: the chatterbox engine is never imported here.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

from vozonda_api.plugins.types import PluginKind
from vozonda_api.providers import chatterbox, tts_engines


def test_meta_fields():
    meta = chatterbox.META
    assert meta.id == "chatterbox"
    assert meta.kind == PluginKind.TTS_ENGINE
    assert meta.renderer == "render_chatterbox.py"
    assert meta.license == "MIT"
    assert meta.commercial_use is True
    assert meta.supports_emotion_instructions is True
    assert meta.supports_paralinguistic_tags is False


def test_is_installed_false_when_paths_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(chatterbox, "RENDER_PY", str(tmp_path / "no-such-python"))
    monkeypatch.setattr(chatterbox, "VOICES_DIR", tmp_path / "no-such-dir")
    assert chatterbox.is_installed() is False


def test_is_installed_false_without_wavs(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")
    voices = tmp_path / "voices"
    voices.mkdir()
    monkeypatch.setattr(chatterbox, "RENDER_PY", str(fake_py))
    monkeypatch.setattr(chatterbox, "VOICES_DIR", voices)
    assert chatterbox.is_installed() is False


def test_is_installed_true_with_interpreter_and_wav(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "host_f.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(chatterbox, "RENDER_PY", str(fake_py))
    monkeypatch.setattr(chatterbox, "VOICES_DIR", voices)
    assert chatterbox.is_installed() is True


def test_discovered_via_tts_engines():
    assert "chatterbox" in tts_engines(refresh=True)


@pytest.fixture()
def renderer():
    """Import render_chatterbox without triggering the engine import in main()."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    try:
        mod = importlib.import_module("vozonda_api.render_chatterbox")
        yield mod
    finally:
        sys.path.pop(0)


def test_emotion_params(renderer):
    assert renderer.emotion_params("neutral") == (0.5, 0.5)
    assert renderer.emotion_params("excited") == (0.8, 0.3)
    assert renderer.emotion_params("energetic") == (0.8, 0.3)
    assert renderer.emotion_params("calm") == (0.3, 0.6)
    assert renderer.emotion_params("dramatic") == (0.7, 0.4)
    assert renderer.emotion_params("bored") == (0.5, 0.5)
    assert renderer.emotion_params("") == (0.5, 0.5)


def test_language_id_for(renderer):
    assert renderer.language_id_for("en") == "en"
    assert renderer.language_id_for("de") == "de"
    assert renderer.language_id_for("English") == "en"
    assert renderer.language_id_for("German") == "de"
    assert renderer.language_id_for("Japanese") == "ja"
    assert renderer.language_id_for("klingon") == "en"
    assert renderer.language_id_for("") == "en"


def test_clean_text(renderer):
    assert renderer.clean_text("hello [laughs] world") == "hello  world"
    assert renderer.clean_text("(sighs) ok") == "ok"
    assert renderer.clean_text("  plain  ") == "plain"


def test_resolve_reference_inside_dir(renderer, tmp_path):
    ref = renderer.resolve_reference("host_f.wav", tmp_path)
    assert ref == (tmp_path / "host_f.wav").resolve()


def test_resolve_reference_rejects_escape(renderer, tmp_path):
    with pytest.raises(ValueError):
        renderer.resolve_reference("../outside.wav", tmp_path)
    with pytest.raises(ValueError):
        renderer.resolve_reference("/etc/passwd", tmp_path)


def test_voice_config_defaults(renderer):
    assert renderer.voice_config({}, "A") == {
        "timbre": renderer.DEFAULT_VOICE,
        "speed": 1.0,
        "emotion": "neutral",
    }
    assert renderer.voice_config({"A": "cb_host_m"}, "A")["timbre"] == "cb_host_m"
    vc = renderer.voice_config({"A": {"timbre": "cb_host_m", "speed": 1.2, "emotion": "calm"}}, "A")
    assert vc == {"timbre": "cb_host_m", "speed": 1.2, "emotion": "calm"}


def test_renderer_runs_without_vozonda_api_on_the_path(tmp_path):
    """The pipeline runs the renderer as a plain file under the engine venv, where
    httpx is missing. Importing the provider from there crashed every render."""
    import subprocess

    script = Path(chatterbox.__file__).resolve().parents[1] / "render_chatterbox.py"
    code = (
        "import runpy, sys; sys.modules['httpx'] = None; sys.modules['vozonda_api.providers'] = None; "
        f"m = runpy.run_path({str(script)!r}); print(m['sample_for']('cb_host_f'))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "host_f.wav"


def test_renderer_defaults_and_sample_names_match_the_provider():
    rc = importlib.import_module("vozonda_api.render_chatterbox")
    assert rc.render_py_default() == chatterbox.RENDER_PY or "VOZONDA_CHATTERBOX_PY" in os.environ
    assert Path(rc.voices_dir_default()) == chatterbox.VOICES_DIR or "VOZONDA_CHATTERBOX_VOICES" in os.environ
    for spk in chatterbox.SPEAKERS:
        assert rc.sample_for(spk["id"]) == spk["sample"], spk
