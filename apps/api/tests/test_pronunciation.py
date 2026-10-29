"""Tests for the pronunciation dictionary module."""

from vozonda_api.pronunciation import (
    apply_pronunciations,
    apply_pronunciations_segments,
    entries_from_global_and_show,
    validate_entries,
)


class TestValidateEntries:
    def test_valid_single_entry(self):
        entries = [{"term": "foo", "say": "fuu"}]
        result = validate_entries(entries)
        assert result == [{"term": "foo", "say": "fuu", "match_case": False}]

    def test_valid_multiple_entries(self):
        entries = [
            {"term": "alpha", "say": "al-fa"},
            {"term": "beta", "say": "bee-ta"},
        ]
        result = validate_entries(entries)
        assert len(result) == 2
        assert result[0]["term"] == "alpha"
        assert result[1]["term"] == "beta"

    def test_match_case_preserved(self):
        entries = [{"term": "Foo", "say": "fuh", "match_case": True}]
        result = validate_entries(entries)
        assert result[0]["match_case"] is True

    def test_match_case_defaults_false(self):
        entries = [{"term": "Foo", "say": "fuh"}]
        result = validate_entries(entries)
        assert result[0]["match_case"] is False

    def test_strips_whitespace(self):
        entries = [{"term": "  foo  ", "say": "  bar  "}]
        result = validate_entries(entries)
        assert result[0]["term"] == "foo"
        assert result[0]["say"] == "bar"

    def test_deduplicates_by_lowercase_term(self):
        entries = [
            {"term": "foo", "say": "fuu"},
            {"term": "FOO", "say": "fwee"},
        ]
        result = validate_entries(entries)
        assert len(result) == 1
        assert result[0]["term"] == "foo"

    def test_none_input_returns_none(self):
        assert validate_entries(None) is None

    def test_non_list_input_returns_none(self):
        assert validate_entries("not a list") is None

    def test_too_many_entries_returns_none(self):
        entries = [{"term": f"e{i}", "say": f"s{i}"} for i in range(501)]
        assert validate_entries(entries) is None

    def test_invalid_entry_returns_none(self):
        entries = [{"term": "foo"}]  # missing 'say'
        assert validate_entries(entries) is None

    def test_empty_term_returns_none(self):
        entries = [{"term": "", "say": "bar"}]
        assert validate_entries(entries) is None

    def test_term_too_long_returns_none(self):
        entries = [{"term": "x" * 101, "say": "bar"}]
        assert validate_entries(entries) is None

    def test_non_dict_entry_returns_none(self):
        entries = ["just a string"]
        assert validate_entries(entries) is None

    def test_empty_list_returns_empty_list(self):
        assert validate_entries([]) == []


class TestApplyPronunciations:
    def test_replaces_word(self):
        result = apply_pronunciations("hello foo world", [{"term": "foo", "say": "fuu"}])
        assert result == "hello fuu world"

    def test_no_match_returns_original(self):
        result = apply_pronunciations("hello world", [{"term": "foo", "say": "fuu"}])
        assert result == "hello world"

    def test_case_insensitive_by_default(self):
        result = apply_pronunciations("Hello FOO world", [{"term": "foo", "say": "fuu"}])
        assert result == "Hello fuu world"

    def test_case_sensitive_when_set(self):
        result = apply_pronunciations(
            "Hello FOO world",
            [{"term": "FOO", "say": "fuu", "match_case": True}],
        )
        assert result == "Hello fuu world"
        result2 = apply_pronunciations(
            "Hello foo world",
            [{"term": "FOO", "say": "fuu", "match_case": True}],
        )
        assert result2 == "Hello foo world"

    def test_longer_terms_first(self):
        entries = [
            {"term": "cooper", "say": "coo-per"},
            {"term": "cooperatives", "say": "coop-er-a-tives"},
        ]
        result = apply_pronunciations("cooper cooperatives", entries)
        assert result == "coo-per coop-er-a-tives"

    def test_no_pronunciations_returns_original(self):
        result = apply_pronunciations("hello", [])
        assert result == "hello"
        result2 = apply_pronunciations("hello", None)
        assert result2 == "hello"

    def test_replaces_all_occurrences(self):
        result = apply_pronunciations("foo bar foo", [{"term": "foo", "say": "fuu"}])
        assert result == "fuu bar fuu"

    def test_does_not_replace_substring(self):
        result = apply_pronunciations("foobar", [{"term": "foo", "say": "fuu"}])
        assert result == "foobar"


class TestApplyPronunciationsSegments:
    def test_transforms_segment_text(self):
        segments = [{"text": "hello foo"}]
        result = apply_pronunciations_segments(
            segments, [{"term": "foo", "say": "fuu"}]
        )
        assert result[0]["text"] == "hello fuu"

    def test_returns_new_list(self):
        segments = [{"text": "hello"}]
        result = apply_pronunciations_segments(segments, [{"term": "x", "say": "y"}])
        assert result is not segments
        assert result[0]["text"] == "hello"

    def test_returns_original_when_no_pronunciations(self):
        segments = [{"text": "hello"}]
        result = apply_pronunciations_segments(segments, None)
        assert result is segments

    def test_returns_original_when_empty(self):
        segments = [{"text": "hello"}]
        result = apply_pronunciations_segments(segments, [])
        assert result is segments

    def test_preserves_other_segment_fields(self):
        segments = [{"text": "hello foo", "start": 0.0}]
        result = apply_pronunciations_segments(
            segments, [{"term": "foo", "say": "fuu"}]
        )
        assert result[0]["start"] == 0.0


class TestEntriesFromGlobalAndShow:
    def test_global_only(self):
        def get_setting(key):
            if key == "tts.pronunciations":
                return '[{"term": "foo", "say": "fuu"}]'
            return None

        result = entries_from_global_and_show(get_setting)
        assert result == [{"term": "foo", "say": "fuu", "match_case": False}]

    def test_no_global_settings(self):
        def get_setting(key):
            return None

        result = entries_from_global_and_show(get_setting)
        assert result is None

    def test_show_overrides_global(self):
        def get_setting(key):
            if key == "tts.pronunciations":
                return '[{"term": "foo", "say": "fuu"}]'
            if key == "show.1.pronunciations":
                return '[{"term": "foo", "say": "fwee"}]'
            return None

        result = entries_from_global_and_show(get_setting, show_num="1")
        assert len(result) == 1
        assert result[0]["say"] == "fwee"

    def test_show_adds_new_term(self):
        def get_setting(key):
            if key == "tts.pronunciations":
                return '[{"term": "foo", "say": "fuu"}]'
            if key == "show.1.pronunciations":
                return '[{"term": "bar", "say": "baar"}]'
            return None

        result = entries_from_global_and_show(get_setting, show_num="1")
        assert len(result) == 2
        terms = {e["term"] for e in result}
        assert "foo" in terms
        assert "bar" in terms

    def test_invalid_json_returns_none(self):
        def get_setting(key):
            if key == "tts.pronunciations":
                return "not json"
            return None

        result = entries_from_global_and_show(get_setting)
        assert result is None

    def test_empty_global(self):
        def get_setting(key):
            if key == "tts.pronunciations":
                return "[]"
            return None

        result = entries_from_global_and_show(get_setting)
        assert result is None


# ── review fixes (2026-10-27) ─────────────────────────────────────────────────

import sqlite3  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import vozonda_api.jobs as jobs_mod  # noqa: E402
from vozonda_api import settings_store as ss  # noqa: E402
from vozonda_api.pronunciation import apply_pronunciations  # noqa: E402


def test_terms_with_punctuation_match_like_words():
    entries = [{"term": "Dr.", "say": "Doctor", "match_case": False},
               {"term": "C++", "say": "C plus plus", "match_case": False}]
    assert apply_pronunciations("Ask Dr. Lee about C++ today.", entries) == "Ask Doctor Lee about C plus plus today."


def test_say_text_is_literal_and_never_replaced_again():
    entries = [{"term": "Nginx", "say": r"engine x \1", "match_case": False},
               {"term": "engine", "say": "motor", "match_case": False}]
    assert apply_pronunciations("Nginx runs", entries) == r"engine x \1 runs"


def test_match_case_entry_matches_only_its_spelling():
    entries = [{"term": "SQL", "say": "sequel", "match_case": True}]
    assert apply_pronunciations("SQL and sql", entries) == "sequel and sql"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    jobs_mod.init_db()
    ss.ensure_table()
    from vozonda_api.main import app
    return TestClient(app)


def test_global_list_over_the_api(api):
    r = api.put("/pronunciations", json={"entries": [{"term": "Vozonda", "say": "vo zon da"}]})
    assert r.status_code == 200 and r.json()[0]["say"] == "vo zon da"
    assert api.get("/pronunciations").json()[0]["term"] == "Vozonda"
    assert api.put("/pronunciations", json={"entries": [{"term": "", "say": "x"}]}).status_code == 422


def test_show_list_by_the_shows_real_slug(api):
    slug = api.post("/shows", json={"name": "Law Notes"}).json()["slug"]
    r = api.put(f"/shows/{slug}/pronunciations", json={"entries": [{"term": "GDPR", "say": "G D P R"}]})
    assert r.status_code == 200
    assert api.get(f"/shows/{slug}/pronunciations").json()[0]["term"] == "GDPR"
    assert api.get("/shows/no-such-show/pronunciations").status_code == 404


@pytest.mark.asyncio
async def test_voice_stage_applies_the_episodes_show_list_and_keeps_the_script(api, monkeypatch):
    """The per-show list reaches the engine; the lines the transcript is built from stay as written."""
    from vozonda_api import pipeline

    slug = api.post("/shows", json={"name": "Clinic"}).json()["slug"]
    api.put(f"/shows/{slug}/pronunciations", json={"entries": [{"term": "Ibuprofen", "say": "eye bew pro fen"}]})
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("INSERT INTO jobs (id, url, state, title, created_at, show_slug, updated_at) "
                  "VALUES ('j1', 'https://example.com/a', 'running', 't', 1700000000, ?, 1700000000)", (slug,))
    seen = {}

    async def fake_local(store, job_id, lines, workdir, **kw):
        seen["text"] = lines[0]["text"]
        return workdir / "x.wav"

    monkeypatch.setattr(pipeline, "_voice_local", fake_local)
    lines = [{"speaker": "A", "text": "Take Ibuprofen with food."}]
    from pathlib import Path
    await pipeline._voice(jobs_mod.JobStore(), "j1", lines, Path("/tmp"))
    assert seen["text"] == "Take eye bew pro fen with food."
    assert lines[0]["text"] == "Take Ibuprofen with food."
