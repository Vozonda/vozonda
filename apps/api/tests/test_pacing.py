"""Pacing (maintainer 2026-09-23): faster global defaults, but meditation and asmr keep
their slow pacing unless the episode sets its own."""

import pytest

from vozonda_api import pipeline


@pytest.fixture()
def globals_fast(monkeypatch):
    values = {"voice.speed": "1.12", "voice.gap_ms": "260"}
    monkeypatch.setattr(pipeline, "get_setting_safe", lambda k: values.get(k))


def _with_profile(monkeypatch, profile):
    monkeypatch.setattr(pipeline, "_voice_profile", lambda store, job_id: profile)


def test_regular_styles_use_the_global_pacing(globals_fast, monkeypatch):
    _with_profile(monkeypatch, {})
    assert pipeline._pacing(None, "j", "balanced") == (1.12, 260)


def test_calm_styles_keep_their_slow_pacing(globals_fast, monkeypatch):
    _with_profile(monkeypatch, {})
    assert pipeline._pacing(None, "j", "meditation") == (0.85, 600)
    assert pipeline._pacing(None, "j", "asmr") == (0.9, 650)


def test_the_episode_profile_wins_over_everything(globals_fast, monkeypatch):
    _with_profile(monkeypatch, {"speed": 0.95, "gap_ms": 400})
    assert pipeline._pacing(None, "j", "asmr") == (0.95, 400)
    assert pipeline._pacing(None, "j", "balanced") == (0.95, 400)


def test_defaults_without_any_setting(monkeypatch):
    monkeypatch.setattr(pipeline, "get_setting_safe", lambda k: None)
    _with_profile(monkeypatch, {})
    assert pipeline._pacing(None, "j", "balanced") == (1.0, 380)
