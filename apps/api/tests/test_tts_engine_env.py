"""VOZONDA_TTS_ENGINE sets the engine of a fresh install (CPU docker quickstart: piper)."""

from vozonda_api import settings_store as ss


def test_env_engine_applies_until_a_setting_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    ss.ensure_table()
    monkeypatch.setenv("VOZONDA_TTS_ENGINE", "piper")
    assert ss.get_setting("tts.engine") == "piper"
    ss.set_setting("tts.engine", "kokoro")
    assert ss.get_setting("tts.engine") == "kokoro"  # an explicit choice wins


def test_unknown_env_engine_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    ss.ensure_table()
    monkeypatch.setenv("VOZONDA_TTS_ENGINE", "no-such-engine")
    assert ss.get_setting("tts.engine") is None
