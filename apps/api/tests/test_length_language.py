"""Per-language speaking rate for length planning (VOZONDA-LEN-LANG).

Tests the fallback order, per-language budgets, and the post-render
_record_wpm helper that writes tts.wpm.<engine>.<lang> keys.
"""

import pytest

from vozonda_api.length import DEFAULT_WPM, measured_wpm, word_budget
from vozonda_api.pipeline import _record_wpm


def test_measured_wpm_fallback_order():
    """Lang key > engine key > default."""
    settings = {
        "tts.wpm.qwen_tts": "150",
        "tts.wpm.qwen_tts.de": "100",
    }
    # Language-specific key wins
    assert measured_wpm("qwen_tts", settings, "de") == 100.0
    # Engine key used when no lang key for that language
    assert measured_wpm("qwen_tts", settings, "en") == 150.0
    assert measured_wpm("qwen_tts", settings, "fr") == 150.0
    # Engine key used when lang is None
    assert measured_wpm("qwen_tts", settings, None) == 150.0
    # Default when engine has no key at all
    assert measured_wpm("unknown_engine", {}, None) == DEFAULT_WPM
    assert measured_wpm("unknown_engine", {}, "de") == DEFAULT_WPM


def test_word_budget_uses_language():
    """word_budget differs for de vs en when both keys exist."""
    settings = {
        "tts.wpm.qwen_tts": "150",
        "tts.wpm.qwen_tts.de": "100",
    }
    # German uses 100 wpm -> 10 min = 1000 words
    assert word_budget(10, "qwen_tts", settings, "de") == 1000
    # English uses 150 wpm -> 10 min = 1500 words
    assert word_budget(10, "qwen_tts", settings, "en") == 1500
    # No language falls back to engine key
    assert word_budget(10, "qwen_tts", settings, None) == 1500
    # Unknown language falls to engine key
    assert word_budget(10, "qwen_tts", settings, "fr") == 1500


def test_word_budget_case_insensitive_language():
    """Language codes are lowercased."""
    settings = {"tts.wpm.qwen_tts.de": "100"}
    assert word_budget(5, "qwen_tts", settings, "DE") == 500
    assert word_budget(5, "qwen_tts", settings, "De") == 500
    assert word_budget(5, "qwen_tts", settings, "de") == 500


def test_record_wpm_writes_language_key(tmp_path, monkeypatch):
    """Post-render update writes tts.wpm.<engine>.<lang> when language known."""
    from vozonda_api import settings_store

    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "jobs.db")
    settings_store.ensure_table()

    # Record a German WPM measurement
    _record_wpm("qwen_tts", "de", 103.5)

    # Language-specific key should be written
    assert settings_store.get_setting("tts.wpm.qwen_tts.de") == "103.5"
    # Engine key should remain untouched
    assert settings_store.get_setting("tts.wpm.qwen_tts") is None


def test_record_wpm_writes_engine_key_when_no_language(tmp_path, monkeypatch):
    """Post-render update writes tts.wpm.<engine> when language unknown."""
    from vozonda_api import settings_store

    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "jobs.db")
    settings_store.ensure_table()

    _record_wpm("qwen_tts", None, 140.0)

    assert settings_store.get_setting("tts.wpm.qwen_tts") == "140"
    assert settings_store.get_setting("tts.wpm.qwen_tts.de") is None


def test_record_wpm_rolling_average_on_language_key(tmp_path, monkeypatch):
    """Rolling average works on the language-specific key."""
    from vozonda_api import settings_store

    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "jobs.db")
    settings_store.ensure_table()

    # First measurement
    _record_wpm("qwen_tts", "de", 100.0)
    assert settings_store.get_setting("tts.wpm.qwen_tts.de") == "100"

    # Second measurement: rolling average with weight 0.2
    # 100 * 0.8 + 110 * 0.2 = 102
    _record_wpm("qwen_tts", "de", 110.0)
    assert settings_store.get_setting("tts.wpm.qwen_tts.de") == "102"


def test_record_wpm_engine_key_untouched_when_lang_key_written(tmp_path, monkeypatch):
    """Engine key stays untouched when language key is written."""
    from vozonda_api import settings_store

    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "jobs.db")
    settings_store.ensure_table()

    # Pre-populate engine key
    settings_store.set_setting("tts.wpm.qwen_tts", "150")

    # Record language-specific measurement
    _record_wpm("qwen_tts", "de", 103.5)

    # Language key written
    assert settings_store.get_setting("tts.wpm.qwen_tts.de") == "103.5"
    # Engine key unchanged
    assert settings_store.get_setting("tts.wpm.qwen_tts") == "150"


def test_record_wpm_case_insensitive_language_key(tmp_path, monkeypatch):
    """Language key is lowercased."""
    from vozonda_api import settings_store

    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "jobs.db")
    settings_store.ensure_table()

    _record_wpm("qwen_tts", "DE", 103.5)
    assert settings_store.get_setting("tts.wpm.qwen_tts.de") == "103.5"


def test_settings_store_accepts_lang_keys(tmp_path, monkeypatch):
    """settings_store validation allows tts.wpm.<engine>.<lang> keys."""
    from vozonda_api import settings_store

    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "jobs.db")
    settings_store.ensure_table()

    # Should not raise
    assert settings_store.set_setting("tts.wpm.qwen_tts.de", "103.5") == "103.5"
    assert settings_store.set_setting("tts.wpm.qwen_tts.en", "134.6") == "134.6"
    assert settings_store.set_setting("tts.wpm.kokoro.fr", "999") == "400"  # clamped
    assert settings_store.get_setting("tts.wpm.qwen_tts.de") == "103.5"
    assert settings_store.get_setting("tts.wpm.qwen_tts.en") == "134.6"
    assert settings_store.get_setting("tts.wpm.kokoro.fr") == "400"