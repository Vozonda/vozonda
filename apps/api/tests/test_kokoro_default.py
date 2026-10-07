"""Kokoro is the CPU quickstart engine, Piper renders the languages Kokoro lacks.

No network, no model files: the renderer subprocess is mocked and the
download helper runs against a stubbed urlopen.
"""

import asyncio
import re
import sys
import types
import urllib.error
from pathlib import Path

from vozonda_api import pipeline
from vozonda_api import settings_store as ss
from vozonda_api.jobs import JobStore
from vozonda_api.providers import kokoro_supports_language, resolve_voice_engine


EXPECTED_MAP = {
    "en": "en-us",
    "es": "es",
    "fr": "fr-fr",
    "it": "it",
    "pt": "pt-br",
    "hi": "hi",
    "ja": "ja",
    "zh": "zh",
}


def _render_kokoro():
    import importlib

    return importlib.import_module("vozonda_api.render_kokoro")


def test_language_map():
    rk = _render_kokoro()
    assert rk.KOKORO_LANG_MAP == EXPECTED_MAP
    assert rk.kokoro_lang_for("en") == "en-us"
    assert rk.kokoro_lang_for("fr") == "fr-fr"
    assert rk.kokoro_lang_for("pt") == "pt-br"
    assert rk.kokoro_lang_for("es") == "es"
    assert rk.kokoro_lang_for("English") == "en-us"
    assert rk.kokoro_lang_for("French") == "fr-fr"


def test_default_voice_per_language():
    rk = _render_kokoro()
    for lang in EXPECTED_MAP:
        voice = rk.default_voice_for(lang)
        assert isinstance(voice, str) and voice
    assert rk.default_voice_for("en") == "af_bella"
    assert rk.default_voice_for("xx") == rk.DEFAULT_VOICE


def test_provider_map_matches_renderer():
    from vozonda_api.providers import kokoro as kok

    rk = _render_kokoro()
    assert kok.KOKORO_LANG_MAP == rk.KOKORO_LANG_MAP
    assert set(kok.KOKORO_SUPPORTED_LANGS) == set(EXPECTED_MAP)


def test_fallback_rule_keeps_supported_languages():
    for lang in EXPECTED_MAP:
        engine, msg = resolve_voice_engine("kokoro", lang)
        assert engine == "kokoro"
        assert msg is None


def test_fallback_rule_german_renders_with_piper():
    engine, msg = resolve_voice_engine("kokoro", "de")
    assert engine == "piper"
    assert msg == "kokoro has no de, using piper"


def test_fallback_rule_unknown_code_renders_with_piper():
    engine, msg = resolve_voice_engine("kokoro", "xx")
    assert engine == "piper"
    assert msg == "kokoro has no xx, using piper"


def test_fallback_rule_leaves_other_engines_alone():
    assert resolve_voice_engine("piper", "de") == ("piper", None)
    assert resolve_voice_engine("qwen_tts", "de") == ("qwen_tts", None)
    assert kokoro_supports_language("de") is False
    assert kokoro_supports_language("en") is True
    assert kokoro_supports_language("xx") is False


def test_installed_check_uses_kokoro_onnx():
    src = (Path(__file__).resolve().parents[1] / "src" / "vozonda_api" / "providers" / "__init__.py").read_text()
    assert "kokoro_onnx" in src
    assert re.search(r"^\s*import kokoro\s*$", src, re.MULTILINE) is None
    kok_src = (Path(__file__).resolve().parents[1] / "src" / "vozonda_api" / "providers" / "kokoro.py").read_text()
    assert "kokoro_onnx" in kok_src


def test_installed_check_detects_kokoro_onnx(tmp_path, monkeypatch):
    from vozonda_api import providers as prov

    fake = types.ModuleType("kokoro_onnx")
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake)
    monkeypatch.delenv("VOZONDA_KOKORO_URL", raising=False)
    engines = prov._probe_installed_engines()
    kok = next(e for e in engines if e["id"] == "kokoro")
    assert kok["installed"] is True


def test_fresh_install_env_kokoro_resolves(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    ss.ensure_table()
    monkeypatch.setenv("VOZONDA_TTS_ENGINE", "kokoro")
    assert ss.get_setting("tts.engine") == "kokoro"


def test_download_helper_builds_expected_paths(tmp_path, monkeypatch):
    rk = _render_kokoro()
    monkeypatch.setenv("VOZONDA_KOKORO_DIR", str(tmp_path / "kok"))
    model, voices = rk.model_paths()
    assert model == tmp_path / "kok" / "kokoro-v1.0.onnx"
    assert voices == tmp_path / "kok" / "voices-v1.0.bin"
    direct = rk.model_paths(tmp_path / "other")
    assert direct == (tmp_path / "other" / "kokoro-v1.0.onnx", tmp_path / "other" / "voices-v1.0.bin")


def test_download_helper_raises_clear_error_when_offline(tmp_path, monkeypatch):
    import urllib.request

    rk = _render_kokoro()

    def _offline(*a, **k):
        raise urllib.error.URLError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    try:
        rk.ensure_models(tmp_path / "empty")
    except RuntimeError as exc:
        assert "offline" in str(exc).lower() or "could not download" in str(exc).lower()
    else:
        raise AssertionError("ensure_models should raise when offline")


class _Stop(Exception):
    pass


def _voice_renderer(tmp_path, monkeypatch, language, source_lang):
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(
        "vozonda_api.settings_store.get_setting",
        lambda k: "kokoro" if k == "tts.engine" else None,
    )
    store = JobStore()
    store.create("j-kok", "https://example.org/article", language=language)
    if source_lang:
        store.add_stage_meta("j-kok", "extract", source_lang=source_lang)

    seen = {}

    async def no_render(*a, **k):
        seen["renderer"] = str(a[1]) if len(a) > 1 else ""
        raise _Stop

    monkeypatch.setattr(pipeline.asyncio, "create_subprocess_exec", no_render)
    lines = [{"speaker": "A", "text": "Hello."}, {"speaker": "B", "text": "Hi there."}]
    try:
        asyncio.run(pipeline._voice_local(store, "j-kok", lines, tmp_path, fmt="dialog", language=language))
    except _Stop:
        pass
    return seen


def test_pipeline_uses_kokoro_renderer_for_english(tmp_path, monkeypatch):
    seen = _voice_renderer(tmp_path, monkeypatch, "en", None)
    assert seen["renderer"].endswith("render_kokoro.py")


def test_pipeline_falls_back_to_piper_for_german(tmp_path, monkeypatch, capsys):
    seen = _voice_renderer(tmp_path, monkeypatch, "de", None)
    assert seen["renderer"].endswith("render_piper.py")
    assert "kokoro has no de, using piper" in capsys.readouterr().out


def test_pipeline_auto_detects_then_falls_back(tmp_path, monkeypatch, capsys):
    seen = _voice_renderer(tmp_path, monkeypatch, "auto", "de")
    assert seen["renderer"].endswith("render_piper.py")
    assert "kokoro has no de, using piper" in capsys.readouterr().out


def test_pipeline_auto_english_stays_kokoro(tmp_path, monkeypatch):
    seen = _voice_renderer(tmp_path, monkeypatch, "auto", "en")
    assert seen["renderer"].endswith("render_kokoro.py")


def test_renderer_runs_without_httpx(tmp_path):
    import subprocess

    import vozonda_api.providers.kokoro as kok

    script = Path(kok.__file__).resolve().parents[1] / "render_kokoro.py"
    code = (
        "import runpy, sys; sys.modules['httpx'] = None; "
        f"m = runpy.run_path({str(script)!r}); "
        "print(m['kokoro_lang_for']('fr') + '/' + m['default_voice_for']('fr'))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "fr-fr/ff_siwis"


def test_download_never_leaves_a_partial_file_under_the_final_name(tmp_path, monkeypatch):
    """A killed download (container stop, OOM) must not leave a truncated model that
    the next start takes for complete: write to .part, rename when finished."""
    import urllib.request

    from vozonda_api import render_kokoro as rk

    dest = tmp_path / "kokoro-v1.0.onnx"
    seen_during_write = {}

    class _Resp:
        def __init__(self):
            self.n = 0

        def read(self, _size):
            self.n += 1
            if self.n == 1:
                seen_during_write["final_exists"] = dest.exists()
                return b"x" * 10
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    rk._download("https://example.invalid/m", dest)
    assert seen_during_write["final_exists"] is False
    assert dest.read_bytes() == b"x" * 10
    assert not list(tmp_path.glob("*.part"))
