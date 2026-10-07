"""Hallucination-Guard & Source-Grounded Insights tests (DUE-077 / #262).

Covers:
- normalize_for_match / verify_quote_exists verbatim matching
- calculate_factuality_score
- lint_takeaways threshold >=0.85, filler & density guards
- lint_executive_summary
- lint_insights overall gate
- insights._parse_insights_json and heuristic fallback
"""

import asyncio

from vozonda_api import insights
from vozonda_api.script_lint import (
    FACTUALITY_THRESHOLD,
    calculate_factuality_score,
    lint_executive_summary,
    lint_insights,
    lint_takeaways,
    normalize_for_match,
    verify_quote_exists,
)


def test_normalize_collapses_whitespace_and_case():
    assert normalize_for_match("  Hello   World ") == "hello world"
    assert normalize_for_match("HeLLo\t\nworld") == "hello world"


def test_normalize_curly_quotes_and_dashes():
    assert normalize_for_match("\u201cHello\u201d") == '"hello"'
    assert normalize_for_match("foo\u2014bar") == "foo-bar"
    assert normalize_for_match("a\u00a0b") == "a b"


def test_verify_quote_exists_verbatim():
    source = "The quick brown fox jumps over the lazy dog. Second sentence here."
    assert verify_quote_exists("quick brown fox", source)
    assert verify_quote_exists("QUICK BROWN FOX", source)
    assert not verify_quote_exists("hallucinated claim not in source", source)


def test_verify_quote_curly_vs_straight():
    source = "He said \u201cactual quote\u201d yesterday."
    assert verify_quote_exists('"actual quote"', source)
    assert verify_quote_exists("\u201cactual quote\u201d", 'He said "actual quote" yesterday.')


def test_verify_quote_too_short_rejected():
    assert not verify_quote_exists("hi", "hi there long source text that contains hi")
    assert not verify_quote_exists("", "some source")


def test_factuality_score_all_verified():
    source = "Alpha beta gamma delta epsilon. Zeta eta theta iota kappa."
    tks = [
        {"source_quote": "Alpha beta gamma"},
        {"source_quote": "Zeta eta theta"},
    ]
    assert calculate_factuality_score(tks, source) == 1.0


def test_factuality_score_partial():
    source = "Alpha beta gamma delta epsilon."
    tks = [
        {"source_quote": "Alpha beta gamma"},
        {"source_quote": "hallucinated nonsense not present"},
        {"source_quote": "delta epsilon"},
    ]
    # 2 of 3 verified => 0.667
    score = calculate_factuality_score(tks, source)
    assert score == 0.667


def test_factuality_empty_is_zero():
    assert calculate_factuality_score([], "some source") == 0.0


def test_lint_takeaways_passes_threshold():
    source = (
        "Bitcoin is a peer to peer electronic cash system. "
        "Miners secure the network with proof of work. "
        "Lightning enables instant payments off chain. "
        "Self custody means you hold your keys. "
        "Nostr is a decentralized social protocol."
    )
    tks = [
        {"id": "t1", "title": "Peer to peer cash", "text": "Bitcoin moves value without banks.", "source_quote": "Bitcoin is a peer to peer electronic cash system"},
        {"id": "t2", "title": "Proof of work security", "text": "Miners burn energy to secure history.", "source_quote": "Miners secure the network with proof of work"},
        {"id": "t3", "title": "Lightning instant payments", "text": "Off chain channels enable instant settlement.", "source_quote": "Lightning enables instant payments off chain"},
    ]
    result = lint_takeaways(tks, source)
    assert result["factuality_score"] >= FACTUALITY_THRESHOLD
    assert result["passed"] is True
    assert result["verified"] == 3


def test_lint_takeaways_fails_threshold():
    source = "Only one true sentence here. The rest is unrelated."
    tks = [
        {"id": "t1", "title": "Good", "text": "A grounded insight.", "source_quote": "Only one true sentence here"},
        {"id": "t2", "title": "Bad", "text": "Hallucinated claim number one.", "source_quote": "This quote does not exist in source"},
        {"id": "t3", "title": "Also bad", "text": "Another hallucinated claim.", "source_quote": "Another fake quote not present"},
    ]
    result = lint_takeaways(tks, source)
    assert result["factuality_score"] < FACTUALITY_THRESHOLD
    assert result["passed"] is False
    assert any("below threshold" in w for w in result["warnings"])


def test_lint_takeaways_flags_filler():
    source = "The study shows that self custody matters. " + "x" * 200
    tks = [
        {"id": "t1", "title": "Self custody", "text": "This article discusses self custody benefits.", "source_quote": "The study shows that self custody matters"},
    ]
    result = lint_takeaways(tks, source)
    assert any("filler" in w.lower() for w in result["warnings"])


def test_lint_takeaways_missing_quote():
    source = "Some source text with enough length to pass."
    tks = [{"id": "t1", "title": "Title", "text": "Some insight text here that is dense.", "source_quote": ""}]
    result = lint_takeaways(tks, source)
    assert any("missing source_quote" in w for w in result["warnings"])


def test_lint_takeaways_density_too_many():
    source = "word " * 500
    tks = [
        {"id": f"t{i}", "title": f"T{i}", "text": f"Insight {i} with some words here.", "source_quote": "word word word word word"}
        for i in range(6)
    ]
    result = lint_takeaways(tks, source)
    assert any("too many" in w for w in result["warnings"])


def test_lint_executive_summary_pass():
    source = "Sovereign AI runs on local hardware with private inference."
    summary = "Run AI locally, keep data private, own your stack."
    quote = "Sovereign AI runs on local hardware"
    result = lint_executive_summary(summary, quote, source)
    assert result["passed"] is True
    assert result["verified"] is True


def test_lint_executive_filler_fails():
    source = "Models run locally on DGX Spark."
    summary = "This article discusses local models."
    result = lint_executive_summary(summary, None, source)
    assert result["passed"] is False
    assert any("filler" in w.lower() for w in result["warnings"])


def test_lint_insights_combined():
    source = (
        "Bitcoin is a peer to peer electronic cash system. "
        "Miners secure the network with proof of work. "
        "Lightning enables instant payments."
    )
    tks = [
        {"id": "t1", "title": "Peer cash", "text": "Move value without banks.", "source_quote": "Bitcoin is a peer to peer electronic cash system"},
        {"id": "t2", "title": "Mining", "text": "Energy secures history.", "source_quote": "Miners secure the network with proof of work"},
        {"id": "t3", "title": "Lightning", "text": "Instant off chain payments.", "source_quote": "Lightning enables instant payments"},
    ]
    result = lint_insights("Peer cash with mining and lightning.", "Bitcoin is a peer to peer electronic cash system", tks, source)
    assert result["factuality_score"] >= 0.85
    assert result["passed"] is True


def test_parse_insights_json_valid():
    raw = """
    {
      "executive_summary": "Source distilled into two sentences, dense and grounded.",
      "executive_quote": "Source sentence one",
      "key_takeaways": [
        {"id":"t1","title":"First insight","text":"Insight one dense.","source_quote":"Source sentence one","section_idx":0},
        {"id":"t2","title":"Second insight","text":"Insight two dense.","source_quote":"Source sentence two","section_idx":1},
        {"id":"t3","title":"Third insight","text":"Insight three dense.","source_quote":"Source sentence three","section_idx":2}
      ]
    }
    """
    exec_text, exec_quote, tks = insights._parse_insights_json(raw)
    assert exec_text.startswith("Source distilled")
    assert exec_quote == "Source sentence one"
    assert len(tks) == 3
    assert tks[0]["source_quote"] == "Source sentence one"


def test_parse_insights_json_missing_summary_raises():
    raw = '{"key_takeaways": [{"title":"T","text":"X","source_quote":"Y"}]}'
    try:
        insights._parse_insights_json(raw)
        assert False, "should raise"
    except ValueError as e:
        assert "executive_summary" in str(e) or "missing" in str(e).lower()


def test_heuristic_takeaways_always_grounded():
    source = (
        "First sentence about sovereign AI and local models running privately. "
        "Second sentence explaining Nostr is a decentralized social protocol. "
        "Third sentence covering Lightning payments for value exchange."
    )
    exec_text, exec_quote, tks = insights._heuristic_takeaways(source, max_items=3)
    assert exec_text
    assert exec_quote
    assert 1 <= len(tks) <= 3
    for tk in tks:
        assert tk.get("source_quote")
        assert verify_quote_exists(str(tk["source_quote"]), source)


def test_extract_insights_heuristic_fallback(monkeypatch):
    """If LLM fails, extract_insights returns heuristic grounded takeaways."""
    body = "Alpha sentence one is here. Beta sentence two is here. Gamma sentence three is here."

    async def fake_call(prompt: str) -> str:
        raise RuntimeError("llm down")

    monkeypatch.setattr(insights, "_call_llm", fake_call)
    exec_text, _exec_quote, tks = asyncio.run(insights.extract_insights(body))
    assert exec_text
    assert len(tks) >= 1
    for tk in tks:
        assert verify_quote_exists(str(tk["source_quote"]), body)


def test_extract_insights_with_mock_llm(monkeypatch):
    body = "Bitcoin enables peer to peer cash. Lightning scales it. Nostr decentralizes social."
    fake_json = """
    {
      "executive_summary": "Peer cash, scaled by Lightning, social via Nostr.",
      "executive_quote": "Bitcoin enables peer to peer cash",
      "key_takeaways": [
        {"id":"t1","title":"Peer cash","text":"Bitcoin moves value without intermediaries.","source_quote":"Bitcoin enables peer to peer cash","section_idx":0},
        {"id":"t2","title":"Lightning scales","text":"Off chain payments are instant.","source_quote":"Lightning scales it","section_idx":1},
        {"id":"t3","title":"Nostr social","text":"Social without servers.","source_quote":"Nostr decentralizes social","section_idx":2}
      ]
    }
    """

    async def fake_call(prompt: str) -> str:
        return fake_json

    monkeypatch.setattr(insights, "_call_llm", fake_call)
    exec_text, exec_quote, tks = asyncio.run(insights.extract_insights(body))
    assert "Peer cash" in exec_text
    assert exec_quote == "Bitcoin enables peer to peer cash"
    assert len(tks) == 3
    assert all(tk.get("source_quote") for tk in tks)


def test_pipeline_attach_insights_stores_with_factuality(tmp_path, monkeypatch):
    """Integration: _attach_insights writes executive_* and key_takeaways to job row."""
    import vozonda_api.jobs as jobs_mod
    from vozonda_api.jobs import JobStore
    from vozonda_api.pipeline import _attach_insights

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = JobStore()
    job_id = "test-insights-guard"
    body = "Sovereign AI runs on local hardware. Nostr keeps social decentralized. Lightning moves sats instantly."
    store.create(job_id, body, style="balanced", fmt="dialog")
    store.set_stage_running(job_id, "script")

    fake_json = """
    {
      "executive_summary": "Sovereign stack: local AI, decentralized social, instant sats.",
      "executive_quote": "Sovereign AI runs on local hardware",
      "key_takeaways": [
        {"id":"t1","title":"Sovereign AI","text":"AI runs locally, privately.","source_quote":"Sovereign AI runs on local hardware","section_idx":0},
        {"id":"t2","title":"Nostr social","text":"Decentralized social without servers.","source_quote":"Nostr keeps social decentralized","section_idx":1},
        {"id":"t3","title":"Lightning sats","text":"Instant settlement off chain.","source_quote":"Lightning moves sats instantly","section_idx":2}
      ]
    }
    """

    async def fake_call(prompt: str) -> str:
        return fake_json

    monkeypatch.setattr(insights, "_call_llm", fake_call)

    async def run():
        tks = await _attach_insights(store, job_id, body, style="balanced", language="auto")
        return tks

    tks = asyncio.run(run())
    job = store.get(job_id)
    assert job.get("executive_summary") == "Sovereign stack: local AI, decentralized social, instant sats."
    assert job.get("executive_quote") == "Sovereign AI runs on local hardware"
    assert job.get("key_takeaways") is not None
    assert len(job["key_takeaways"]) == 3
    assert job.get("factuality_score") == 1.0
    assert all("source_quote" in tk for tk in job["key_takeaways"])
    # lint meta stored on script stage
    script_stage = next((s for s in job["stages"] if s["name"] == "script"), None)
    assert script_stage is not None
    meta = script_stage.get("meta", {})
    assert "factuality_score" in meta or "insights_lint" in meta
    assert len(tks) == 3


def test_takeaway_timestamp_finalization(tmp_path, monkeypatch):
    """_finalize_insights_timings maps section_idx to script t0."""
    import vozonda_api.jobs as jobs_mod
    from vozonda_api.jobs import JobStore
    from vozonda_api.pipeline import _attach_insights, _finalize_insights_timings

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs2.db")
    store = JobStore()
    job_id = "test-ts-finalize"
    body = "Sentence one. Sentence two. Sentence three. Sentence four."
    store.create(job_id, body, style="balanced", fmt="dialog")
    # create script with t0s
    store.update(job_id, script=[
        {"speaker": "A", "text": "Line 0", "t0": 0.0},
        {"speaker": "B", "text": "Line 1", "t0": 5.5},
        {"speaker": "A", "text": "Line 2", "t0": 12.0},
        {"speaker": "B", "text": "Line 3", "t0": 18.0},
    ])

    fake_json = """
    {
      "executive_summary": "Four sentences summarized.",
      "executive_quote": "Sentence one",
      "key_takeaways": [
        {"id":"t1","title":"One","text":"Insight one.","source_quote":"Sentence one","section_idx":0},
        {"id":"t2","title":"Two","text":"Insight two.","source_quote":"Sentence two","section_idx":2},
        {"id":"t3","title":"Three","text":"Insight three.","source_quote":"Sentence three","section_idx":3}
      ]
    }
    """

    async def fake_call(prompt: str) -> str:
        return fake_json

    monkeypatch.setattr(insights, "_call_llm", fake_call)
    asyncio.run(_attach_insights(store, job_id, body))
    _finalize_insights_timings(store, job_id)
    job = store.get(job_id)
    tks = job.get("key_takeaways") or []
    assert tks[0].get("timestamp_ms") == 0
    assert tks[1].get("timestamp_ms") == 12000
    assert tks[2].get("timestamp_ms") == 18000
    assert tks[0].get("time_formatted") == "0:00"
    assert tks[1].get("time_formatted") == "0:12"


# ---- JSON repair tests (token cutoff recovery) ----


def test_repair_unclosed_object():
    raw = '{"executive_summary":"hello","key_takeaways":[]'
    exec_text, _, tks = insights._parse_insights_json(raw)
    assert exec_text == "hello"
    assert tks == []


def test_repair_unclosed_string_in_object():
    raw = '{"executive_summary":"unterminated","key_takeaways":[{"id":"t1","title":"T","text":"broken string'
    exec_text, _, tks = insights._parse_insights_json(raw)
    assert exec_text == "unterminated"
    assert len(tks) == 1


def test_repair_trailing_comma_in_object():
    raw = '{"executive_summary":"hello","key_takeaways":[],"}'
    exec_text, _, tks = insights._parse_insights_json(raw)
    assert exec_text == "hello"


def test_repair_insights_truncated_with_thinking():
    """Thinking + truncated JSON object is repaired."""
    raw = "<thinking>lots of reasoning</thinking>\n{\"executive_summary\":\"short\",\n\"key_takeaways\":[{\"id\":\"t1\",\"title\":\"T\",\"text\":\"cut"
    exec_text, _, tks = insights._parse_insights_json(raw)
    assert exec_text == "short"
    assert len(tks) == 1
    assert tks[0]["text"] == "cut"
