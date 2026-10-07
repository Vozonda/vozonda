"""Tests for bench/metrics.py: KB path, language selection, markup_hits, bc_distinct, question_share."""

import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

import pytest

# bench/ is at repo root, 4 levels up from this file
_bench_dir = Path(__file__).resolve().parent.parent.parent.parent / "bench"
sys.path.insert(0, str(_bench_dir))
import metrics as metrics  # noqa: I001, A004
import report as report_mod  # noqa: I001, A004


class TestDefaultKBPath:
    """Test that the default KB directory resolves to bench/kb."""

    def test_default_kb_dir_resolves_to_bench_kb(self):
        default = metrics._default_kb_dir()
        assert default.name == "kb"
        assert default.parent.name == "bench"
        assert default.exists()

    def test_default_kb_dir_has_english_files(self):
        kb = metrics._default_kb_dir()
        assert (kb / "back-channels.md").exists()
        assert (kb / "repair-templates.md").exists()

    def test_default_kb_dir_has_german_files(self):
        kb = metrics._default_kb_dir()
        assert (kb / "back-channels-de.md").exists()
        assert (kb / "repair-templates-de.md").exists()

    def test_bench_kb_dir_env_var(self):
        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / "custom_kb"
            env_path.mkdir()
            (env_path / "back-channels.md").write_text("# nothing\n")
            (env_path / "repair-templates.md").write_text("# nothing\n")
            with warnings.catch_warnings(record=True):
                os.environ["BENCH_KB_DIR"] = str(env_path)
                result = metrics._default_kb_dir()
                assert result == env_path
            del os.environ["BENCH_KB_DIR"]


class TestLanguageSelection:
    """Test that the language parameter selects the correct KB files."""

    def test_english_language_uses_default_files(self):
        kb = metrics._default_kb_dir()
        turns = [
            {"speaker": "A", "text": "Right. Exactly. Wow!"},
            {"speaker": "B", "text": "Yes, that is correct."},
        ]
        with warnings.catch_warnings(record=True):
            result = metrics.compute_script_metrics(turns, language="en")
        assert result["bc_distinct"] is not None
        assert result["bc_distinct"] >= 1

    def test_german_language_uses_de_files(self):
        kb = metrics._default_kb_dir()
        turns = [
            {"speaker": "A", "text": "Genau. Mhm, ja."},
            {"speaker": "B", "text": "Stimmt, und dann…"},
        ]
        with warnings.catch_warnings(record=True):
            result = metrics.compute_script_metrics(turns, language="de")
        assert result["bc_distinct"] is not None
        assert result["bc_distinct"] >= 1

    def test_missing_kb_file_gives_null_not_zero(self):
        kb = metrics._default_kb_dir()
        turns = [
            {"speaker": "A", "text": "Hello world."},
        ]
        bc_path = kb / "back-channels.md"
        backup = kb / "back-channels.md.bak"
        bc_path.rename(backup)
        try:
            with pytest.warns(UserWarning, match="back-channels"):
                result = metrics.compute_script_metrics(turns, language="en")
            assert result["bc_distinct"] is None
            assert result["bc_repeat_violations"] is None
            assert result["bare_mhm"] is None
        finally:
            backup.rename(bc_path)

    def test_missing_repair_file_gives_null_not_zero(self):
        kb = metrics._default_kb_dir()
        turns = [
            {"speaker": "A", "text": "Hello world."},
        ]
        rep_path = kb / "repair-templates.md"
        backup = kb / "repair-templates.md.bak"
        rep_path.rename(backup)
        try:
            with pytest.warns(UserWarning, match="repair-templates"):
                result = metrics.compute_script_metrics(turns, language="en")
            assert result["repair_count"] is None
        finally:
            backup.rename(rep_path)


class TestMarkupHits:
    """Test that markup_hits only counts real markup, not acronyms."""

    def test_acronyms_do_not_count(self):
        turns = [
            {"speaker": "A", "text": "RSS and MPEG are standards. ARD WDR NZZ COVID."},
            {"speaker": "B", "text": "Those are all acronyms under 6 letters."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] == 0

    def test_real_markup_counts(self):
        turns = [
            {"speaker": "A", "text": "[laughs] (sighs) <break/>"},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] == 3

    def test_bracket_tags(self):
        turns = [
            {"speaker": "A", "text": "[laugh] He said hello."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] == 1

    def test_paren_stage_directions(self):
        turns = [
            {"speaker": "A", "text": "(sighs) That is unfortunate."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] == 1

    def test_ssml_tags(self):
        turns = [
            {"speaker": "A", "text": "<break time=\"500ms\"/> Hello."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] == 1

    def test_long_allcaps_counts(self):
        turns = [
            {"speaker": "A", "text": "AMAZINGLY that was incredible."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] >= 1

    def test_short_allcaps_does_not_count(self):
        turns = [
            {"speaker": "A", "text": "RSS is the format. WDR is the station."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] == 0

    def test_mixed_markup_and_acronyms(self):
        turns = [
            {"speaker": "A", "text": "[sigh] RSS is complex. (pause) <break/>"},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["markup_hits"] == 3


class TestBcDistinct:
    """Test that bc_distinct correctly counts distinct back-channels."""

    def test_bc_distinct_on_script_with_en_backchannels(self):
        turns = [
            {"speaker": "A", "text": "Right."},
            {"speaker": "B", "text": "Exactly."},
            {"speaker": "A", "text": "Wow!"},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["bc_distinct"] == 3

    def test_bc_distinct_german(self):
        turns = [
            {"speaker": "A", "text": "Genau."},
            {"speaker": "B", "text": "Stimmt."},
            {"speaker": "A", "text": "Krass."},
        ]
        result = metrics.compute_script_metrics(turns, language="de")
        assert result["bc_distinct"] >= 2


class TestQuestionShare:
    """Test that question_share is within the range 0.12 - 0.25."""

    def test_question_share_within_range(self):
        turns = [
            {"speaker": "A", "text": "What do you think about this?"},
            {"speaker": "B", "text": "I am not sure."},
            {"speaker": "A", "text": "Let me explain."},
            {"speaker": "B", "text": "That makes sense."},
            {"speaker": "A", "text": "Okay, next topic."},
            {"speaker": "B", "text": "Sure."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert 0.12 <= result["question_share"] <= 0.25

    def test_question_share_below_range(self):
        turns = [
            {"speaker": "A", "text": "This is a statement."},
            {"speaker": "B", "text": "That is true."},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["question_share"] < 0.12

    def test_question_share_above_range(self):
        turns = [
            {"speaker": "A", "text": "Really?"},
            {"speaker": "B", "text": "What?"},
        ]
        result = metrics.compute_script_metrics(turns)
        assert result["question_share"] > 0.25


class TestReportQuestionShareRange:
    """Test that report.py uses a range check for question_share."""

    def test_question_share_range_check_passes(self):
        assert report_mod._check("question_share", 0.15) is True
        assert report_mod._check("question_share", 0.20) is True
        assert report_mod._check("question_share", 0.12) is True
        assert report_mod._check("question_share", 0.25) is True

    def test_question_share_range_check_fails(self):
        assert report_mod._check("question_share", 0.11) is False
        assert report_mod._check("question_share", 0.26) is False
        assert report_mod._check("question_share", 0.0) is False
        assert report_mod._check("question_share", 1.0) is False

    def test_question_share_null(self):
        assert report_mod._check("question_share", None) is None


class TestLoadPhrases:
    """Test that load_phrases_from_md handles both backtick and quote styles."""

    def test_load_backtick_phrases(self):
        kb = metrics._default_kb_dir()
        phrases = metrics.load_phrases_from_md(kb / "back-channels.md")
        assert "Right." in phrases
        assert "Exactly." in phrases
        assert "Wow!" in phrases

    def test_load_quote_phrases(self):
        kb = metrics._default_kb_dir()
        phrases = metrics.load_phrases_from_md(kb / "back-channels-de.md")
        assert "Genau." in phrases
        assert "Stimmt." in phrases
        assert "Krass." in phrases

    def test_load_repair_templates(self):
        kb = metrics._default_kb_dir()
        phrases = metrics.load_phrases_from_md(kb / "repair-templates.md")
        assert "Let me back up." in phrases
        assert "Actually no, it's…" in phrases

    def test_load_german_repair_templates(self):
        kb = metrics._default_kb_dir()
        phrases = metrics.load_phrases_from_md(kb / "repair-templates-de.md")
        assert "Moment, ich meine…" in phrases
        assert "Warte, anders gesagt…" in phrases