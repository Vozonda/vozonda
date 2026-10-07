"""Dia2 engine: registration, pure renderer helpers, and running as a file."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vozonda_api.providers import dia2, tts_engines
from vozonda_api.render_dia2 import (
    build_turns,
    chunk_script,
    chunk_turns,
    language_ok,
    reference_spans,
    turn_durations,
    turn_starts,
)

SCRIPT = Path(dia2.__file__).resolve().parents[1] / "render_dia2.py"


def _segs(*pairs):
    return [{"speaker": s, "text": t} for s, t in pairs]


def test_registered_as_tts_engine():
    assert "dia2" in tts_engines()
    assert dia2.META.renderer == "render_dia2.py"
    assert dia2.META.commercial_use is True


def test_language_accepts_the_name_the_pipeline_passes():
    assert language_ok("English") and language_ok("en")
    assert not language_ok("German")


def test_speakers_map_in_order_of_appearance_even_when_b_speaks_first():
    turns = build_turns(_segs(("B", "hi there"), ("A", "hello")))
    assert [t["tag"] for t in turns] == ["[S1]", "[S2]"]


def test_three_speakers_are_refused():
    with pytest.raises(ValueError):
        build_turns(_segs(("A", "a"), ("B", "b"), ("C", "c")))


def test_stage_directions_and_colons_are_cleaned():
    (t,) = build_turns(_segs(("A", "[laughs] Well: that (sighs) works")))
    assert t["text"] == "Well that works"


def test_chunks_never_split_a_turn_and_skip_empty_turns():
    turns = build_turns(_segs(("A", "one two three"), ("B", ""), ("A", "four five"), ("B", "six")))
    chunks = chunk_turns(turns, max_words=4)
    assert [[t["seg"] for t in c] for c in chunks] == [[0], [2, 3]]
    assert chunk_script(chunks[1]) == "[S1] four five [S2] six"


def test_turn_starts_follow_the_word_timestamps():
    chunk = chunk_turns(build_turns(_segs(("A", "hello there"), ("B", "hi"))))[0]
    stamps = [("hello", 0.0), ("there", 0.4), ("", 0.6), ("hi", 1.2)]
    assert turn_starts(chunk, stamps) == [0.0, 1.2]
    assert turn_durations(chunk, [0.0, 1.2], 2.0) == [1.2, 0.8]


def test_misaligned_timestamps_fall_back_to_text_length():
    chunk = chunk_turns(build_turns(_segs(("A", "aaaa"), ("B", "bbbbbbbbbbbb"))))[0]
    assert turn_starts(chunk, [("aaaa", 0.0)]) is None
    assert turn_durations(chunk, None, 4.0) == [1.0, 3.0]


def test_reference_clip_per_speaker_uses_the_longest_turn_and_clip_relative_times():
    chunk = chunk_turns(build_turns(_segs(("A", "short"), ("B", "b words here"), ("A", "a long turn now"))))[0]
    stamps = [("short", 0.0), ("b", 1.0), ("words", 2.0), ("here", 3.0),
              ("a", 5.0), ("long", 6.0), ("turn", 7.0), ("now", 8.0)]
    spans = reference_spans(chunk, stamps, total_s=10.0)
    # A's first turn is 1 s (under the minimum), its second turn 5 s
    assert spans["[S1]"][:2] == (5.0, 10.0)
    assert spans["[S1]"][2] == [("a", 0.0), ("long", 1.0), ("turn", 2.0), ("now", 3.0)]
    assert spans["[S2]"][:2] == (1.0, 5.0)


def test_renderer_runs_as_a_file_without_vozonda_api(tmp_path):
    """The pipeline runs renderers as plain files in the engine venv (no httpx)."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"segments": [], "language": "English", "out": str(tmp_path / "o.wav")}))
    code = ("import runpy, sys; sys.modules['httpx'] = None; sys.modules['vozonda_api.providers'] = None; "
            f"sys.argv = ['r', '--config', {str(cfg)!r}]; runpy.run_path({str(SCRIPT)!r}, run_name='__main__')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60)
    assert "no audio produced" in out.stderr, out.stderr


def test_curated_reference_needs_wav_and_words_and_a_plain_id(tmp_path):
    from vozonda_api.render_dia2 import curated_reference

    (tmp_path / "host_m.wav").write_bytes(b"RIFF")
    (tmp_path / "host_m.json").write_text(json.dumps({"words": [["hello", 0.0], ["there", 0.4]]}))
    path, words = curated_reference(tmp_path, "host_m")
    assert path.endswith("host_m.wav") and words == [("hello", 0.0), ("there", 0.4)]
    assert curated_reference(tmp_path, "missing") is None
    assert curated_reference(tmp_path, "../host_m") is None


def test_renderer_voices_dir_matches_the_provider(monkeypatch):
    from vozonda_api.render_dia2 import voices_dir

    monkeypatch.delenv("VOZONDA_DIA2_VOICES", raising=False)
    assert voices_dir() == dia2.VOICES_DIR


def test_default_voices_are_curated_speakers():
    from vozonda_api.render_dia2 import DEFAULT_VOICES

    ids = {s["id"] for s in dia2.SPEAKERS}
    assert set(DEFAULT_VOICES.values()) <= ids


def test_sample_path_only_for_known_voices(tmp_path, monkeypatch):
    monkeypatch.setattr(dia2, "VOICES_DIR", tmp_path)
    (tmp_path / "host_m.wav").write_bytes(b"RIFF")
    assert dia2.sample_path("host_m") == tmp_path / "host_m.wav"
    assert dia2.sample_path("../etc/passwd") is None
    assert dia2.sample_path("host_f") is None


def test_speakers_for_works_before_anything_discovered_the_engines():
    """A fresh process asking for plugin voices first got an empty list."""
    code = ("from vozonda_api.voices import speakers_for; "
            "print(len(speakers_for('dia2')), len(speakers_for('chatterbox')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60)
    assert out.stdout.split() == [str(len(dia2.SPEAKERS)), "5"], out.stderr
