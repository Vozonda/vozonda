from vozonda_api import pipeline as pl
from vozonda_api import settings_store as ss


def test_name_keys_strip_and_clamp(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    ss.ensure_table()
    assert ss.set_setting("voice.a.name", "  Mira  ") == "Mira"
    assert ss.set_setting("voice.b.name", "x" * 40) == "x" * 24
    assert ss.get_setting("voice.a.name") == "Mira"


def test_stored_line_keeps_letter_and_rides_name():
    out = pl._stored_line({"speaker": "A", "text": "hi"}, {"A": "Mira"})
    assert out == {"speaker": "A", "text": "hi", "name": "Mira"}
    # no custom name for this letter: nothing added
    assert pl._stored_line({"speaker": "C", "text": "yo"}, {"A": "Mira"}) == {
        "speaker": "C",
        "text": "yo",
    }
    # narration speaker never matches a letter key
    assert pl._stored_line({"speaker": "Narrator", "text": "s"}, {"A": "M"}) == {
        "speaker": "Narrator",
        "text": "s",
    }


def test_host_names_reads_settings_only_non_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    ss.ensure_table()
    ss.set_setting("voice.a.name", "Mira")
    ss.set_setting("voice.c.name", "   ")
    assert pl._host_names() == {"A": "Mira"}
