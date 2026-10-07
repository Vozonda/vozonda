"""Tests for voice sample generation and sample_url exposure."""

import shutil
import sys
from pathlib import Path

from vozonda_api.voices import (
    KOKORO_SPEAKERS,
    all_speaker_tables,
    sample_url,
    speakers_for,
)

# Make the scripts dir importable for the generator's plan function.
_repo_root = Path(__file__).resolve().parents[3]
_scripts_dir = _repo_root / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
from generate_voice_samples import plan

# ── sample_url ──────────────────────────────────────────────────────

def test_sample_url_returns_url_when_file_exists(tmp_path: Path, monkeypatch):
    """sample_url returns the URL path when the mp3 exists."""
    sample_dir = tmp_path / "media" / "samples" / "voices"
    sample_dir.mkdir(parents=True)
    sample_file = sample_dir / "kokoro_af_bella.mp3"
    sample_file.write_bytes(b"fake mp3 data")

    monkeypatch.setenv("VOZONDA_WEB_PUBLIC", str(tmp_path))
    url = sample_url("kokoro", "af_bella")
    assert url == "/media/samples/voices/kokoro_af_bella.mp3"


def test_sample_url_returns_none_when_missing(tmp_path: Path, monkeypatch):
    """sample_url returns None when the sample file does not exist."""
    monkeypatch.setenv("VOZONDA_WEB_PUBLIC", str(tmp_path))
    url = sample_url("kokoro", "af_bella")
    assert url is None


def test_sample_url_returns_none_when_file_empty(tmp_path: Path, monkeypatch):
    """sample_url returns None for a zero-byte file."""
    sample_dir = tmp_path / "media" / "samples" / "voices"
    sample_dir.mkdir(parents=True)
    (sample_dir / "kokoro_af_bella.mp3").write_text("")

    monkeypatch.setenv("VOZONDA_WEB_PUBLIC", str(tmp_path))
    url = sample_url("kokoro", "af_bella")
    assert url is None


# ── speaker table enrichment ───────────────────────────────────────

def test_all_speaker_tables_includes_sample_url_key(monkeypatch):
    """Every speaker entry in speaker_tables carries the 'sample_url' key."""
    tables = all_speaker_tables()
    for engine_id, speakers in tables.items():
        for spk in speakers:
            assert "sample_url" in spk, f"{engine_id} {spk['id']} missing sample_url"


def test_speakers_for_without_enrich():
    """speakers_for without enrich returns the base dict."""
    speakers = speakers_for("kokoro")
    assert len(speakers) == len(KOKORO_SPEAKERS)
    for s in speakers:
        assert "sample_url" not in s


def test_speakers_for_with_enrich(tmp_path, monkeypatch):
    """speakers_for with enrich=True adds sample_url (None without a file)."""
    monkeypatch.setenv("VOZONDA_WEB_PUBLIC", str(tmp_path))
    speakers = speakers_for("kokoro", enrich=True)
    for s in speakers:
        assert "sample_url" in s
        assert s["sample_url"] is None  # no files exist in tests


# ── plan function ───────────────────────────────────────────────────

def test_plan_returns_one_entry_per_voice(tmp_path: Path):
    """plan returns exactly one entry per voice of an engine."""
    items = plan("kokoro", sample_dir_path=tmp_path)
    ids_in_plan = {item[1] for item in items}  # item[1] = voice_id
    speaker_ids = {s["id"] for s in KOKORO_SPEAKERS}
    assert ids_in_plan == speaker_ids


def test_plan_skips_existing_files(tmp_path: Path):
    """plan skips voices that already have a sample file."""
    (tmp_path / "kokoro_af_bella.mp3").write_bytes(b"fake")

    items = plan("kokoro", sample_dir_path=tmp_path)
    ids_in_plan = {item[1] for item in items}
    assert "af_bella" not in ids_in_plan
    assert len(ids_in_plan) == len(KOKORO_SPEAKERS) - 1


def test_plan_force_includes_existing(tmp_path: Path):
    """plan with force=True includes all voices."""
    (tmp_path / "kokoro_af_bella.mp3").write_bytes(b"fake")

    items = plan("kokoro", force=True, sample_dir_path=tmp_path)
    ids_in_plan = {item[1] for item in items}
    assert "af_bella" in ids_in_plan
    assert len(ids_in_plan) == len(KOKORO_SPEAKERS)


def test_plan_output_format():
    """plan returns tuples of (Path, str, str)."""
    tmp = Path("/tmp/_test_voice_samples_format")
    try:
        tmp.mkdir(exist_ok=True, parents=True)
        items = plan("kokoro", sample_dir_path=tmp)
        for item in items:
            assert len(item) == 3
            out_path, voice_id, text = item
            assert isinstance(out_path, Path)
            assert isinstance(voice_id, str)
            assert isinstance(text, str)
            assert out_path.suffix == ".mp3"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_plan_empty_for_unknown_engine():
    """plan returns empty list for engines with no speakers."""
    items = plan("nonexistent_engine_abc")
    assert items == []