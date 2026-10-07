import pytest

from vozonda_api import settings_store as ss


def test_gap_ms_rejects_nonsense():
    with pytest.raises(ValueError):
        ss.set_setting("voice.gap_ms", "abc")


def test_speed_clamped_to_pipeline_range():
    assert ss.set_setting("voice.speed", "99") == "2"
    assert ss.set_setting("voice.speed", "0.1") == "0.5"


def test_count_is_int_in_range():
    assert ss.set_setting("voice.dialog.count", "7") == "3"
    assert ss.set_setting("voice.dialog.count", "2") == "2"
    ss.set_setting("voice.gap_ms", "380")


def test_research_depth_validation():
    assert ss.set_setting("source.research_depth", "direct") == "direct"
    assert ss.set_setting("source.research_depth", "deep-page") == "deep-page"
    assert ss.set_setting("source.research_depth", "fact-check") == "fact-check"
    assert ss.set_setting("source.research_depth", "contrast") == "contrast"
    with pytest.raises(ValueError):
        ss.set_setting("source.research_depth", "invalid-mode")


def test_tts_engine_validation():
    assert ss.set_setting("tts.engine", "qwen_tts") == "qwen_tts"
    assert ss.set_setting("tts.engine", "voxtral") == "voxtral"
    assert ss.set_setting("tts.engine", "piper") == "piper"
    with pytest.raises(ValueError):
        ss.set_setting("tts.engine", "invalid_tts")


def test_player_defaults_validation():
    assert ss.set_setting("player.default_speed", "1.25") == "1.25"
    assert ss.set_setting("player.default_text_size", "large") == "large"
    assert ss.set_setting("player.karaoke", "0") == "0"
    assert ss.set_setting("player.chapters", "1") == "1"
    assert ss.set_setting("player.autoscroll", "free") == "free"
    assert ss.set_setting("player.boost_placement", "strip") == "strip"

    with pytest.raises(ValueError):
        ss.set_setting("player.default_speed", "3.5")
    with pytest.raises(ValueError):
        ss.set_setting("player.default_text_size", "huge")
    with pytest.raises(ValueError):
        ss.set_setting("player.karaoke", "yes")
    with pytest.raises(ValueError):
        ss.set_setting("player.chapters", "2")
    with pytest.raises(ValueError):
        ss.set_setting("player.autoscroll", "auto")
    with pytest.raises(ValueError):
        ss.set_setting("player.boost_placement", "top")

from vozonda_api.jobs import human_error


def test_human_error_extracts_last_exception_line():
    blob = 'Traceback (most recent call last):\n  File "/x/y.py", line 9\nValueError: bad model config'
    assert human_error(blob) == "ValueError: bad model config"


def test_human_error_single_line_passes_through():
    assert human_error("connection refused") == "connection refused"
    assert "traceback" not in human_error("").lower()
