"""Tests for bench/report.py – report.html and judge_pack.json."""

import json
import sys
from pathlib import Path

# Import report module (bench/ is not a package)
report_dir = Path(__file__).resolve().parent.parent.parent.parent / "bench"
sys.path.insert(0, str(report_dir))
import report as report_mod  # noqa: I001


# ── fixtures ──────────────────────────────────────────────────────────────────

_REF_METRICS = {
    "words": 850,
    "turns": 28,
    "turn_len_mean": 12.3,
    "turn_len_cv": 0.9,
    "short_turn_share": 0.25,
    "question_share": 0.22,
    "speaker_balance": 0.72,
    "bc_distinct": 5,
    "repair_count": 2,
    "overuse_hits": 0,
    "markup_hits": 0,
    "hook_words": 15,
    "duration_s": 320,
    "lufs_i": -16.2,
    "true_peak": -2.1,
    "lra": 8.5,
    "wpm": 160,
    "gap_median_ms": 250,
    "gap_p90_ms": 520,
    "gap_cv": 0.65,
}

_RUNA_METRICS = {
    "words": 820,
    "turns": 26,
    "turn_len_mean": 11.5,
    "turn_len_cv": 0.85,
    "short_turn_share": 0.20,
    "question_share": 0.18,
    "speaker_balance": 0.30,  # FAIL: < 0.4
    "bc_distinct": 4,
    "repair_count": 4,  # FAIL: > 3
    "overuse_hits": 0,
    "markup_hits": 0,
    "hook_words": 20,
    "duration_s": 310,
    "lufs_i": -15.8,
    "true_peak": -1.8,
    "lra": 9.0,
    "wpm": 165,
    "gap_median_ms": 200,
    "gap_p90_ms": 480,
    "gap_cv": 0.55,
    "wer": 0.06,
}

_RUNB_METRICS = {
    "words": 900,
    "turns": 32,
    "turn_len_mean": 14.0,
    "turn_len_cv": 0.70,  # FAIL: < 0.8
    "short_turn_share": 0.28,
    "question_share": 0.12,  # FAIL: < 0.15
    "speaker_balance": 0.55,
    "bc_distinct": 3,
    "repair_count": 2,
    "overuse_hits": 2,  # FAIL: > 0
    "markup_hits": 1,  # FAIL: > 0
    "hook_words": 35,
    "duration_s": 340,
    "lufs_i": -16.0,
    "true_peak": -2.0,
    "lra": 7.5,
    "wpm": 175,
    "gap_median_ms": 300,
    "gap_p90_ms": 600,
    "gap_cv": 0.70,
    "wer": 0.10,  # FAIL: >= 0.08
}

_SOURCES_YAML = """
sources:
  - id: test-src
    url: https://example.com/test
    kind: test
    stresses: everything
""".strip()


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


class TestReportHtml:
    """Tests for report.html generation."""

    def test_report_contains_both_runs_and_targets(
        self, tmp_path: Path,
    ) -> None:
        # --- setup fake data ─────────────────────────────────────────────
        sources_yaml = tmp_path / "sources.yaml"
        sources_yaml.write_text(_SOURCES_YAML, encoding="utf-8")

        refs_dir = tmp_path / "references"
        refs_dir.mkdir()
        _write_json(refs_dir / "test-src.json", {
            "source_id": "test-src",
            "type": "reference",
            "metrics": _REF_METRICS,
        })

        runs_dir = tmp_path / "runs"
        for run_id, metrics in [("run-a", _RUNA_METRICS), ("run-b", _RUNB_METRICS)]:
            rd = runs_dir / run_id / "test-src"
            rd.mkdir(parents=True)
            _write_json(rd / "metrics.json", {
                "source_id": "test-src",
                "type": "run",
                "run_id": run_id,
                "metrics": metrics,
            })

        # --- run report ──────────────────────────────────────────────────
        out_dir = tmp_path
        report_mod.build_report(
            sources=[{"id": "test-src", "url": "https://example.com/test",
                       "kind": "test", "stresses": "everything"}],
            runs_dir=runs_dir,
            refs_dir=refs_dir,
            out_dir=out_dir,
        )

        # --- assertions ─────────────────────────────────────────────────
        html_path = out_dir / "report.html"
        assert html_path.exists()
        html = html_path.read_text()

        # Both run IDs appear in HTML
        assert "run-a" in html, "run-a should appear in report HTML"
        assert "run-b" in html, "run-b should appear in report HTML"
        assert "test-src" in html

        # Reference also in HTML (table column)
        assert "reference" in html

        # Check-mark (pass) and cross-mark (fail) markers present
        assert "\u2713" in html, "check-mark (pass) should be in HTML"
        assert "\u2717" in html, "cross-mark (fail) should be in HTML"
        assert "\u2014" in html, "dash (report-only) should be in HTML"

        # Metric names appear in table rows
        assert "lufs_i" in html
        assert "short_turn_share" in html

        # Target labels appear
        for lbl in ["0.4 - 1.0", "0.15 - 0.35", ">= 0.08", "< 0.08"]:
            if lbl in ["< 0.08"]:  # wer target
                assert lbl in html, f"Target label '{lbl}' should be in HTML"

        # Summary row present (check run ratios)
        # run-a: 4/17 pass, run-b: 12/17 pass (approximate)
        assert "run-a" in html
        assert "run-b" in html

        # Table structure: should have th with scope=col
        assert 'scope="col"' in html

        # Audio elements present
        assert "<audio" in html
        assert "controls" in html

        # Dark mode via prefers-color-scheme
        assert "prefers-color-scheme:dark" in html


class TestJudgePack:
    """Tests for judge_pack.json generation."""

    def test_judge_pack_hides_mapping(
        self, tmp_path: Path,
    ) -> None:
        # --- setup ───────────────────────────────────────────────────────
        sources_yaml = tmp_path / "sources.yaml"
        sources_yaml.write_text(_SOURCES_YAML, encoding="utf-8")

        refs_dir = tmp_path / "references"
        refs_dir.mkdir()
        _write_json(refs_dir / "test-src.json", {
            "source_id": "test-src",
            "type": "reference",
            "metrics": _REF_METRICS,
            "transcript": [
                {"speaker": "host1", "text": "Welcome to the show."},
                {"speaker": "host2", "text": "Today we discuss AI."},
            ],
        })

        runs_dir = tmp_path / "runs"
        for run_id, metrics in [("run-a", _RUNA_METRICS), ("run-b", _RUNB_METRICS)]:
            rd = runs_dir / run_id / "test-src"
            rd.mkdir(parents=True)
            _write_json(rd / "metrics.json", {
                "source_id": "test-src",
                "type": "run",
                "run_id": run_id,
                "metrics": metrics,
                "transcript": [
                    {"speaker": "host1", "text": "Let's begin."},
                    {"speaker": "host2", "text": "Sure."},
                ],
            })

        # --- run report ──────────────────────────────────────────────────
        out_dir = tmp_path
        report_mod.build_report(
            sources=[{"id": "test-src", "url": "https://example.com/test",
                       "kind": "test", "stresses": "everything"}],
            runs_dir=runs_dir,
            refs_dir=refs_dir,
            out_dir=out_dir,
        )

        # --- load and inspect judge pack ─────────────────────────────────
        pack_path = out_dir / "judge_pack.json"
        key_path = out_dir / "judge_key.json"
        assert pack_path.exists()
        assert key_path.exists()

        pack = json.loads(pack_path.read_text())
        key = json.loads(key_path.read_text())

        # Pack should have sources list
        assert "sources" in pack
        assert len(pack["sources"]) >= 1

        source_pack = pack["sources"][0]
        assert source_pack["source_id"] == "test-src"
        assert "candidates" in source_pack
        assert len(source_pack["candidates"]) == 3  # 1 ref + 2 runs

        # Collect all labels from pack
        labels: list[str] = []
        for c in source_pack["candidates"]:
            labels.append(c["label"])
            assert "label" in c
            assert "transcript" in c

        # Labels should be single uppercase letters
        for lbl in labels:
            assert lbl.isupper(), f"Label '{lbl}' should be uppercase letter"
            assert len(lbl) == 1, f"Label '{lbl}' should be single char"

        # --- NO run IDs or 'reference' in pack JSON text ─────────────────
        pack_text = json.dumps(pack, ensure_ascii=False)
        assert "run-a" not in pack_text, "run-a should NOT appear in judge_pack.json"
        assert "run-b" not in pack_text, "run-b should NOT appear in judge_pack.json"
        assert "run_c" not in pack_text  # just in case
        assert "reference" not in pack_text, "'reference' should NOT appear in pack"

        # --- Key file maps labels to actual identities ───────────────────
        for lbl in labels:
            assert lbl in key, f"Label '{lbl}' should be in judge_key.json"
            entry = key[lbl]
            assert "type" in entry

        # Key should have the mapping info
        types_found: set[str] = set()
        for lbl, entry in key.items():
            types_found.add(entry["type"])
        assert "ref" in types_found, "Key should have ref type"
        assert "run" in types_found, "Key should have run type"


class TestReportMetrics:
    """Edge-case tests for check/summary logic."""

    def test_check_pass(self) -> None:
        assert report_mod._check("overuse_hits", 0) is True

    def test_check_fail(self) -> None:
        assert report_mod._check("overuse_hits", 2) is False

    def test_check_none_value(self) -> None:
        assert report_mod._check("wer", None) is None

    def test_check_report_only(self) -> None:
        # words is report-only
        assert report_mod._check("words", 500) is None
        assert report_mod._check("turns", 20) is None

    def test_check_range_pass(self) -> None:
        assert report_mod._check("speaker_balance", 0.7) is True

    def test_check_range_fail_low(self) -> None:
        assert report_mod._check("speaker_balance", 0.3) is False

    def test_check_range_fail_high(self) -> None:
        assert report_mod._check("repair_count", 5) is False

    def test_summary_with_all_pass(self) -> None:
        m = {"overuse_hits": 0, "markup_hits": 0, "wer": 0.05}
        assert report_mod._summary(m) == "3/3"

    def test_summary_with_some_fail(self) -> None:
        m = {"overuse_hits": 0, "markup_hits": 1, "wer": 0.10}
        assert report_mod._summary(m) == "1/3"

    def test_summary_no_metrics(self) -> None:
        assert report_mod._summary({}) == "n/a"

    def test_summary_none_metrics(self) -> None:
        assert report_mod._summary(None) == "n/a"

    def test_cell_marker_pass(self) -> None:
        assert report_mod._mk(True, 1.0) == "\u2713"

    def test_cell_marker_fail(self) -> None:
        assert report_mod._mk(False, 1.0) == "\u2717"

    def test_cell_marker_null(self) -> None:
        assert report_mod._mk(None, None) == "\u2014"


class TestHtmlStructure:
    """HTML structure and accessibility tests."""

    def _make_dirs(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        r = tmp_path / "runs"
        r.mkdir()
        refs = tmp_path / "references"
        refs.mkdir()
        return r, refs, tmp_path

    def test_dark_mode_query(self, tmp_path: Path) -> None:
        runs_d, refs_d, out_d = self._make_dirs(tmp_path)
        report_mod.build_report(
            sources=[{"id": "s", "url": "https://x.com", "kind": "k",
                       "stresses": "s"}],
            runs_dir=runs_d,
            refs_dir=refs_d,
            out_dir=out_d,
        )
        html = (out_d / "report.html").read_text()
        assert "prefers-color-scheme:dark" in html

    def test_viewport_meta(self, tmp_path: Path) -> None:
        runs_d, refs_d, out_d = self._make_dirs(tmp_path)
        report_mod.build_report(
            sources=[{"id": "s", "url": "https://x.com", "kind": "k",
                       "stresses": "s"}],
            runs_dir=runs_d,
            refs_dir=refs_d,
            out_dir=out_d,
        )
        html = (out_d / "report.html").read_text()
        assert 'width=390' in html

    def test_table_scope(self, tmp_path: Path) -> None:
        runs_d, refs_d, out_d = self._make_dirs(tmp_path)
        report_mod.build_report(
            sources=[{"id": "s", "url": "https://x.com", "kind": "k",
                       "stresses": "s"}],
            runs_dir=runs_d,
            refs_dir=refs_d,
            out_dir=out_d,
        )
        html = (out_d / "report.html").read_text()
        assert 'scope="col"' in html

    def test_self_contained_no_js(self, tmp_path: Path) -> None:
        runs_d, refs_d, out_d = self._make_dirs(tmp_path)
        report_mod.build_report(
            sources=[{"id": "s", "url": "https://x.com", "kind": "k",
                       "stresses": "s"}],
            runs_dir=runs_d,
            refs_dir=refs_d,
            out_dir=out_d,
        )
        html = (out_d / "report.html").read_text()
        assert "<script" not in html

# ── real on-disk format (2026-09-25) ──────────────────────────────────────────
# metrics.py writes {"script": {...}, "audio": {...}, "wer": x, "wpm": y};
# references sit next to their audio as <sid>.m4a.metrics.json plus
# <sid>.m4a.transcript.json. The fixtures above used a flat format metrics.py
# never wrote, so report.html showed a dash in every cell while tests passed.

def _real_metrics(words, wpm, q_share):
    return {"script": {"words": words, "turns": 30, "question_share": q_share, "speaker_balance": None},
            "audio": {"duration_s": 1200.0, "lufs_i": -16.5, "gap_median_ms": 285.0},
            "wer": None, "wpm": wpm}


def test_report_reads_the_format_metrics_py_writes(tmp_path):
    refs = tmp_path / "references"
    runs = tmp_path / "runs" / "20260924T0948Z-balanced" / "s1"
    refs.mkdir()
    runs.mkdir(parents=True)
    (refs / "s1.m4a.metrics.json").write_text(json.dumps(_real_metrics(3243, 172.0, 0.37)))
    (refs / "s1.m4a.transcript.json").write_text(json.dumps(
        {"text": "So what is this about? It is about gates. Really?", "word_timestamps": [], "language": "en"}))
    (runs / "metrics.json").write_text(json.dumps(_real_metrics(2551, 141.7, 0.1)))
    (runs / "script.json").write_text(json.dumps(
        [{"speaker": "A", "text": "Why does it matter?"}, {"speaker": "B", "text": "Because gates lie."}]))

    groups = report_mod._group_metrics(tmp_path / "runs", refs)
    assert set(groups) == {"s1"}
    ref = groups["s1"]["ref_metrics"]
    run = groups["s1"]["run_metrics"]["20260924T0948Z-balanced"]
    assert ref["words"] == 3243 and ref["wpm"] == 172.0 and ref["lufs_i"] == -16.5
    assert run["words"] == 2551 and run["wpm"] == 141.7
    # comparable across diarized scripts and undiarized references
    assert ref["questions_per_1k"] == round(2 / 10 * 1000, 1)
    assert run["questions_per_1k"] == round(1 / 7 * 1000, 1)
    # per-turn shares mean nothing on a reference without speakers
    assert "question_share" not in ref
    assert groups["s1"]["ref_transcript"].startswith("So what")
    html = report_mod.generate_html([{"id": "s1"}], groups, [tmp_path / "runs" / "20260924T0948Z-balanced"], tmp_path)
    assert "2551" in html and "141.7" in html


# --- per-style targets from the rhythm profiles (2026-10-02) -----------------

def test_socrates_is_judged_by_its_own_profile_not_the_balanced_rubric():
    from report import _check

    # A asks only questions and talks a quarter of the words: fine for socrates, not for balanced
    assert _check("question_share", 0.48, "socrates") is True
    assert _check("question_share", 0.48, "balanced") is False
    assert _check("speaker_balance", 0.3, "socrates") is True
    assert _check("speaker_balance", 0.3, "balanced") is False


def test_calm_styles_do_not_fail_for_low_variation_and_no_repairs_count_as_right():
    from report import _check

    assert _check("turn_len_cv", 0.3, "asmr") is None
    assert _check("turn_len_cv", 0.3, "balanced") is False
    assert _check("repair_count", 0, "noir") is True  # "Nobody corrects themselves"
    assert _check("repair_count", 0, "debate") is False


def test_without_a_known_style_the_rubric_is_unchanged():
    from report import _check, _style_of

    assert _style_of("20261002T0636Z-balanced") == "balanced"
    assert _style_of("20261002T0636Z-true_crime") == "true_crime"
    assert _check("speaker_balance", 0.3, None) is False
    assert _check("speaker_balance", 0.3, "no_such_style") is False
