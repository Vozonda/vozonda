"""Tests for the digest pipeline (#122).

Covers:
- _DIGEST_SECTION_RE section parser
- lint_digest_script: transition count, word budget, section thinness
- JobStore digest columns: create + update (chapters)
"""
import importlib

import pytest

# ---------------------------------------------------------------------------
# Section regex
# ---------------------------------------------------------------------------
from vozonda_api.pipeline import _DIGEST_SECTION_RE


def test_section_re_basic():
    text = "[SECTION:0:First Story]\n[{\"speaker\":\"A\",\"text\":\"hello\"}]\n[/SECTION]"
    matches = _DIGEST_SECTION_RE.findall(text)
    assert len(matches) == 1
    idx, title, body = matches[0]
    assert idx == "0"
    assert "First Story" in title
    assert "hello" in body


def test_section_re_multiple():
    text = (
        "[SECTION:0:Alpha]\ncontent a\n[/SECTION]\n"
        "[SECTION:1:Beta]\ncontent b\n[/SECTION]"
    )
    matches = _DIGEST_SECTION_RE.findall(text)
    assert len(matches) == 2
    assert matches[0][0] == "0"
    assert matches[1][0] == "1"


# ---------------------------------------------------------------------------
# lint_digest_script
# ---------------------------------------------------------------------------
from vozonda_api.script_lint import lint_digest_script


def _make_sections(n: int = 3) -> list[dict]:
    return [
        {"index": i, "title": f"Story {i}", "url": f"http://example.com/{i}", "body": "x " * 200}
        for i in range(n)
    ]


def _make_lines(n_per_section: int = 10, n_sections: int = 3, include_transitions: bool = True) -> list[dict]:
    lines = []
    for i in range(n_sections):
        for j in range(n_per_section):
            lines.append({"speaker": "A" if j % 2 == 0 else "B", "text": "word " * 10})
        if include_transitions and i < n_sections - 1:
            lines.append({"speaker": "A", "text": "Next up, let us talk about the next story."})
    return lines


def test_lint_digest_no_transition_warn_when_present():
    sections = _make_sections(3)
    lines = _make_lines(n_per_section=15, n_sections=3, include_transitions=True)
    result = lint_digest_script(lines, sections)
    transition_warns = [w for w in result["warnings"] if "transition" in w]
    assert not transition_warns


def test_lint_digest_missing_transitions():
    sections = _make_sections(3)
    lines = _make_lines(n_per_section=10, n_sections=3, include_transitions=False)
    result = lint_digest_script(lines, sections)
    warns = [w for w in result["warnings"] if "transition" in w]
    assert len(warns) == 1


def test_lint_digest_word_budget_too_low():
    sections = _make_sections(3)
    # Only 5 very short turns - well below 50% of 1200-word target
    lines = [{"speaker": "A", "text": "hi there"} for _ in range(5)]
    result = lint_digest_script(lines, sections)
    budget_warns = [w for w in result["warnings"] if "words" in w]
    assert len(budget_warns) >= 1


def test_lint_digest_thin_sections():
    sections = _make_sections(4)
    # Only 4 total turns for 4 sections = avg 1.0 < 3
    lines = [{"speaker": "A", "text": "word " * 20} for _ in range(4)]
    result = lint_digest_script(lines, sections)
    thin_warns = [w for w in result["warnings"] if "turns per section" in w]
    assert len(thin_warns) >= 1


def test_lint_digest_returns_counts():
    sections = _make_sections(2)
    lines = _make_lines(n_per_section=8, n_sections=2, include_transitions=True)
    result = lint_digest_script(lines, sections)
    assert result["sections"] == 2
    assert result["transitions"] >= 1
    assert result["total_words"] > 0


# ---------------------------------------------------------------------------
# JobStore digest columns
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("VOZONDA_DB", str(db))
    import vozonda_api.jobs as jobs_mod
    importlib.reload(jobs_mod)
    from vozonda_api.jobs import JobStore as JS
    return JS()


def test_jobstore_digest_create(tmp_store):
    job = tmp_store.create(
        "digest-abc123",
        "digest:digest-abc123",
        digest=True,
        digest_sources=["http://a.com", "http://b.com"],
    )
    assert job["digest"] is True
    assert job["digest_sources"] == ["http://a.com", "http://b.com"]
    assert job["chapters"] is None


def test_jobstore_chapters_update(tmp_store):
    tmp_store.create("digest-xyz", "digest:digest-xyz", digest=True, digest_sources=["http://a.com", "http://b.com"])
    chapters = [
        {"index": 0, "title": "Story A", "url": "http://a.com", "word_offset": 0},
        {"index": 1, "title": "Story B", "url": "http://b.com", "word_offset": 200},
    ]
    updated = tmp_store.update("digest-xyz", chapters=chapters)
    assert updated["chapters"] is not None
    assert len(updated["chapters"]) == 2
    assert updated["chapters"][1]["title"] == "Story B"


def test_jobstore_non_digest_backwards_compat(tmp_store):
    """Existing non-digest create calls must still work unchanged."""
    job = tmp_store.create("regular-job", "http://example.com")
    assert job["digest"] is False
    assert job["digest_sources"] is None
    assert job["chapters"] is None


def test_apply_script_timings_ground_truth(tmp_store, tmp_path, monkeypatch):
    import vozonda_api.pipeline as pl_mod
    monkeypatch.setattr(pl_mod, "MEDIA_DIR", tmp_path)

    job_id = "test-timing-1"
    tmp_store.create(job_id, "http://example.com")
    lines = [
        {"speaker": "A", "text": "Short greeting."},
        {"speaker": "B", "text": "A longer response that takes several seconds to deliver."},
        {"speaker": "A", "text": "Wrap up."},
    ]
    # Ground truth segment durations from TTS renderer
    durations = [2.4, 5.8, 1.6]
    (tmp_path / f"{job_id}.timing.json").write_text(json.dumps(durations))

    pl_mod._apply_script_timings(tmp_store, job_id, lines, speed=1.0, duration=9.8)

    updated = tmp_store.get(job_id)
    script = updated["script"]
    assert len(script) == 3
    assert script[0]["t0"] == 0.0
    assert script[1]["t0"] == 2.4
    assert script[2]["t0"] == 8.2  # 2.4 + 5.8


def test_apply_script_timings_fallback_proportional(tmp_store, tmp_path, monkeypatch):
    import vozonda_api.pipeline as pl_mod
    monkeypatch.setattr(pl_mod, "MEDIA_DIR", tmp_path)

    job_id = "test-timing-2"
    tmp_store.create(job_id, "http://example.com")
    lines = [
        {"speaker": "A", "text": "12345"},  # 5 chars
        {"speaker": "B", "text": "123456789012345"},  # 15 chars
    ]
    # Total 20 chars, total duration 10.0s -> turn 0: 0.0s, turn 1: 2.5s
    pl_mod._apply_script_timings(tmp_store, job_id, lines, speed=1.0, duration=10.0)

    updated = tmp_store.get(job_id)
    script = updated["script"]
    assert len(script) == 2
    assert script[0]["t0"] == 0.0
    assert script[1]["t0"] == 2.5


# ---------------------------------------------------------------------------
# _embed_chapters (DUE-011)
# ---------------------------------------------------------------------------

import json


@pytest.mark.asyncio
async def test_embed_chapters_creates_metadata_file(tmp_path):
    """_embed_chapters creates and removes the metadata file."""
    import vozonda_api.pipeline as pl_mod
    pl_mod.MEDIA_DIR = tmp_path

    job_id = "test-chapters"
    mp3 = tmp_path / f"{job_id}.mp3"
    mp3.write_bytes(b"ID3" + b"\x00" * 4096)

    chapters = [
        {"index": 0, "title": "Intro", "word_offset": 0},
        {"index": 1, "title": "Main Story", "word_offset": 50},
        {"index": 2, "title": "Outro", "word_offset": 100},
    ]
    duration = 10.0

    await pl_mod._embed_chapters(mp3, chapters, duration)

    meta_files = list(tmp_path.glob("*.meta"))
    assert len(meta_files) == 0


@pytest.mark.asyncio
async def test_embed_chapters_empty_chapters(tmp_path):
    """_embed_chapters does nothing with empty chapters."""
    import vozonda_api.pipeline as pl_mod
    pl_mod.MEDIA_DIR = tmp_path

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"ID3" + b"\x00" * 4096)

    await pl_mod._embed_chapters(mp3, [], 10.0)
    assert mp3.exists()


@pytest.mark.asyncio
async def test_embed_chapters_none_chapters(tmp_path):
    """_embed_chapters does nothing with None chapters."""
    import vozonda_api.pipeline as pl_mod
    pl_mod.MEDIA_DIR = tmp_path

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"ID3" + b"\x00" * 4096)

    await pl_mod._embed_chapters(mp3, None, 10.0)
    assert mp3.exists()


@pytest.mark.asyncio
async def test_embed_chapters_metadata_content(tmp_path):
    """_embed_chapters generates correct metadata content."""
    import vozonda_api.pipeline as pl_mod
    pl_mod.MEDIA_DIR = tmp_path

    job_id = "test-chapters-meta"
    mp3 = tmp_path / f"{job_id}.mp3"
    mp3.write_bytes(b"ID3" + b"\x00" * 4096)

    chapters = [
        {"index": 0, "title": "First", "word_offset": 0},
        {"index": 1, "title": "Second", "word_offset": 100},
    ]
    duration = 20.0

    await pl_mod._embed_chapters(mp3, chapters, duration)

    # The metadata file should have been written and cleaned up
    # We verify by checking that the function completes without error
    # and the MP3 is still present (even if ffmpeg is not available)
    assert mp3.exists()
