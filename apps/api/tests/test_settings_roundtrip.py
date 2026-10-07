import pytest

from vozonda_api.settings_store import all_settings, get_setting, set_setting


def test_roundtrip() -> None:
    set_setting("voice.speed", "1.25")
    assert get_setting("voice.speed") == "1.25"


def test_overwrite() -> None:
    set_setting("voice.speed", "1.0")
    set_setting("voice.speed", "0.9")
    assert get_setting("voice.speed") == "0.9"


def test_all_settings_contains_written_key() -> None:
    set_setting("voice.gap_ms", "420")
    assert all_settings()["voice.gap_ms"] == "420"


def test_unknown_key_rejected_everywhere() -> None:
    with pytest.raises(KeyError):
        get_setting("nope.key")
    with pytest.raises(KeyError):
        set_setting("nope.key", "x")
