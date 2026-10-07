"""Length calibration must persist: until 2026-09-24 set_setting rejected every
tts.wpm.* key, the pipeline swallowed the error and planning stayed on 160 wpm."""

import pytest

from vozonda_api import settings_store


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "jobs.db")
    settings_store.ensure_table()
    yield


def test_wpm_keys_can_be_written_and_read(tmp_settings):
    assert settings_store.set_setting("tts.wpm.qwen_tts", "134.6") == "134.6"
    assert settings_store.get_setting("tts.wpm.qwen_tts") == "134.6"
    assert settings_store.set_setting("tts.wpm.kokoro", "999") == "400"  # clamped


def test_unknown_keys_are_still_rejected(tmp_settings):
    with pytest.raises(KeyError):
        settings_store.set_setting("tts.speed.qwen_tts", "1")
