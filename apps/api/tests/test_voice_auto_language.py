"""'auto' language reaches the voice stage as the detected source language.

Before 2026-09-23 a German article with language=auto got a German script
(the script stage used the detected language) but English default voices
and language "English" in the renderer config.
"""

import asyncio
import json

import pytest

from vozonda_api import pipeline
from vozonda_api.jobs import JobStore
from vozonda_api.voices import DEFAULT_TIMBRE_FOR


class _Stop(Exception):
    pass


def _render_cfg(tmp_path, monkeypatch, language, source_lang):
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    # pin the engine: other tests may leave a different tts.engine behind
    monkeypatch.setattr("vozonda_api.settings_store.get_setting", lambda k: "qwen_tts" if k == "tts.engine" else None)
    store = JobStore()
    store.create("j-lang", "https://de.example.org/artikel", language=language)
    if source_lang:
        store.add_stage_meta("j-lang", "extract", source_lang=source_lang)

    async def no_render(*a, **k):  # the config is written before the renderer starts
        raise _Stop

    monkeypatch.setattr(pipeline.asyncio, "create_subprocess_exec", no_render)
    lines = [{"speaker": "A", "text": "Hallo."}, {"speaker": "B", "text": "Servus."}]
    with pytest.raises(_Stop):
        asyncio.run(pipeline._voice_local(store, "j-lang", lines, tmp_path, fmt="dialog", language=language))
    return json.loads((tmp_path / "j-lang.voice.json").read_text())


def test_auto_uses_the_detected_source_language(tmp_path, monkeypatch):
    cfg = _render_cfg(tmp_path, monkeypatch, "auto", "de")
    assert cfg["language"] == "German"
    assert cfg["voices"]["A"]["timbre"] == DEFAULT_TIMBRE_FOR["de"]["a"]


def test_explicit_language_wins_over_detection(tmp_path, monkeypatch):
    cfg = _render_cfg(tmp_path, monkeypatch, "en", "de")
    assert cfg["language"] == "English"


def test_auto_without_detection_stays_english(tmp_path, monkeypatch):
    cfg = _render_cfg(tmp_path, monkeypatch, "auto", None)
    assert cfg["language"] == "English"
