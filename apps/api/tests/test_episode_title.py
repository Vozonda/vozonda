"""Tests for descriptive episode title generation from script."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from vozonda_api import pipeline
from vozonda_api.jobs import JobStore


def _script_result(raw: str | list, desc: str = ""):
    async def fake(*, prompt: str, **kwargs):
        if isinstance(raw, str):
            import re
            import json

            m = re.search(r"\[.*\]", raw, re.DOTALL)
            lines = json.loads(m.group(0)) if m else []
            tail = raw[m.end():] if m else ""
            dm = re.search(r"DESCRIPTION:\s*(.+)", tail)
            found = dm.group(1).strip().strip('"') if dm else ""
        else:
            lines, found = raw, desc
        return lines, found
    return fake


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.doctor as doc_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(doc_mod, "blocking_problem", lambda: None)

    async def fake_fetch(url):
        return f"<html>{url}</html>"

    async def fake_extract(url, html=None, **kwargs):
        return "Test Title", "Test body. " + "word " * 500, None

    async def fake_voice(*args, **kwargs):
        return tmp_path / "test.wav"

    async def fake_master(*args, **kwargs):
        return tmp_path / "test.mp3"

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(pipeline, "download_og_image", lambda *a, **k: asyncio.sleep(0, result=False), raising=False)
    monkeypatch.setattr(pipeline, "generate_template_cover", lambda *a, **k: asyncio.sleep(0), raising=False)

    return JobStore()


def _run(store, job_id):
    async def go():
        async for _ in pipeline.run_job(store, job_id):
            pass
    asyncio.run(go())


def test_generated_title_replaces_source_title(env, monkeypatch):
    """A generated title from the script replaces the source title."""
    store = env
    job_id = "test-title-gen"
    store.create(job_id, "https://example.com/article", style="balanced", fmt="dialog")

    script_turns = [
        {"speaker": "A", "text": "Bitcoin and Ethereum take different roads to trustless money. Bitcoin uses proof of work."},
        {"speaker": "B", "text": "Ethereum moved to proof of stake. Both achieve consensus but with different tradeoffs."},
        {"speaker": "A", "text": "The security model of Bitcoin relies on hash power. Ethereum relies on staked capital."},
        {"speaker": "B", "text": "This fundamental difference shapes their ecosystems and future development paths."},
    ]
    script_content = '[{"speaker":"A","text":"Bitcoin and Ethereum take different roads to trustless money. Bitcoin uses proof of work."},{"speaker":"B","text":"Ethereum moved to proof of stake. Both achieve consensus but with different tradeoffs."},{"speaker":"A","text":"The security model of Bitcoin relies on hash power. Ethereum relies on staked capital."},{"speaker":"B","text":"This fundamental difference shapes their ecosystems and future development paths."}]\nDESCRIPTION: Bitcoin vs Ethereum comparison'

    generated_title = "Bitcoin vs Ethereum: two roads to trustless money"
    call_count = 0

    async def mock_chat_completion(prov, prompt, max_tokens=4096):
        nonlocal call_count
        call_count += 1
        assert "Source title(s): Test Title" in prompt
        assert "Bitcoin and Ethereum" in prompt
        return generated_title
    monkeypatch.setattr(pipeline, "script_call", _script_result(script_content, ""))
    monkeypatch.setattr(pipeline, "_chat_completion", mock_chat_completion)

    _run(store, job_id)

    job = store.get(job_id)
    assert job["state"] == "done", job.get("error")
    assert job["title"] == generated_title
    assert call_count == 1

    # Verify source_title stored in stage meta
    script_stage = next((s for s in job.get("stages", []) if s["name"] == "script"), None)
    assert script_stage is not None
    meta = script_stage.get("meta", {})
    assert meta.get("source_title") == "Test Title"


def test_llm_failure_keeps_original_title(env, monkeypatch):
    """If LLM fails or returns garbage, the original title is kept."""
    store = env
    job_id = "test-title-fail"
    store.create(job_id, "https://example.com/article", style="balanced", fmt="dialog")

    script_content = '[{"speaker":"A","text":"Some content here."},{"speaker":"B","text":"More content."},{"speaker":"A","text":"Even more content."},{"speaker":"B","text":"Final content."}]\nDESCRIPTION: test'

    call_count = 0

    async def mock_chat_completion_fail(prov, prompt, max_tokens=4096):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("LLM down")
    monkeypatch.setattr(pipeline, "script_call", _script_result(script_content, ""))
    monkeypatch.setattr(pipeline, "_chat_completion", mock_chat_completion_fail)

    _run(store, job_id)

    job = store.get(job_id)
    assert job["state"] == "done", job.get("error")
    assert job["title"] == "Test Title"  # original title kept

    # Verify source_title still stored
    script_stage = next((s for s in job.get("stages", []) if s["name"] == "script"), None)
    assert script_stage is not None
    meta = script_stage.get("meta", {})
    assert meta.get("source_title") == "Test Title"


def test_garbage_llm_reply_keeps_original_title(env, monkeypatch):
    """Invalid LLM reply (too short, too long, multiline) keeps original title."""
    store = env
    job_id = "test-title-garbage"
    store.create(job_id, "https://example.com/article", style="balanced", fmt="dialog")

    script_content = '[{"speaker":"A","text":"Content one."},{"speaker":"B","text":"Content two."},{"speaker":"A","text":"Content three."},{"speaker":"B","text":"Content four."}]\nDESCRIPTION: test'

    call_count = 0

    async def mock_chat_completion_garbage(prov, prompt, max_tokens=4096):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "x" * 100  # too long
        elif call_count == 2:
            return "ok"  # too short
        elif call_count == 3:
            return "line one\nline two"  # multiline
        return "valid title here"
    monkeypatch.setattr(pipeline, "script_call", _script_result(script_content, ""))
    monkeypatch.setattr(pipeline, "_chat_completion", mock_chat_completion_garbage)

    _run(store, job_id)

    job = store.get(job_id)
    assert job["state"] == "done", job.get("error")
    assert job["title"] == "Test Title"  # original title kept after all retries


def test_valid_llm_reply_on_second_provider(env, monkeypatch):
    """If first provider fails, second provider's valid reply is used."""
    store = env
    job_id = "test-title-second"
    store.create(job_id, "https://example.com/article", style="balanced", fmt="dialog")

    script_content = '[{"speaker":"A","text":"Content one."},{"speaker":"B","text":"Content two."},{"speaker":"A","text":"Content three."},{"speaker":"B","text":"Content four."}]\nDESCRIPTION: test'

    call_count = 0

    async def mock_chat_completion_retry(prov, prompt, max_tokens=4096):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("first provider down")
        return "Valid generated title"

    def mock_llm_chain():
        return [
            {"name": "provider1", "base": "http://localhost:1/v1", "model": "test"},
            {"name": "provider2", "base": "http://localhost:2/v1", "model": "test"},
        ]
    monkeypatch.setattr(pipeline, "script_call", _script_result(script_content, ""))
    monkeypatch.setattr(pipeline, "_chat_completion", mock_chat_completion_retry)
    monkeypatch.setattr(pipeline, "llm_chain", mock_llm_chain)

    _run(store, job_id)

    job = store.get(job_id)
    assert job["state"] == "done", job.get("error")
    assert job["title"] == "Valid generated title"


def test_combine_sources_gets_generated_title(env, monkeypatch):
    """Multi-source combine path gets a generated title instead of 'A + B'."""
    store = env
    job_id = "test-combine-title"
    store.create(
        job_id,
        "digest:test-combine-title",
        digest=True,
        digest_sources=["https://btc.example/wp", "https://eth.example/wp"],
        combine=True,
    )

    # Mock for combine path - it calls _run_from_body internally
    script_content = '[{"speaker":"A","text":"Bitcoin uses proof of work for consensus."},{"speaker":"B","text":"Ethereum uses proof of stake instead."},{"speaker":"A","text":"This creates different security models."},{"speaker":"B","text":"Both achieve trustless consensus differently."}]\nDESCRIPTION: combined discussion'

    generated_title = "Bitcoin vs Ethereum: consensus mechanisms compared"

    async def mock_chat_completion(prov, prompt, max_tokens=4096):
        assert "Source title(s):" in prompt
        assert "Bitcoin" in prompt or "Ethereum" in prompt
        return generated_title

    async def fake_fetch(url):
        return f"<html>{url}</html>"

    async def fake_extract(url, html=None, **kwargs):
        name = "Bitcoin Whitepaper" if "btc" in url else "Ethereum Whitepaper"
        return name, f"{name} text. " + "word " * 400, None
    monkeypatch.setattr(pipeline, "script_call", _script_result(script_content, ""))
    monkeypatch.setattr(pipeline, "_chat_completion", mock_chat_completion)
    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)

    _run(store, job_id)

    job = store.get(job_id)
    assert job["state"] == "done", job.get("error")
    # Should NOT be the combined source titles
    assert " + " not in job["title"]
    assert job["title"] == generated_title

    # Verify source_title stored (should be the combo title)
    script_stage = next((s for s in job.get("stages", []) if s["name"] == "script"), None)
    assert script_stage is not None
    meta = script_stage.get("meta", {})
    assert "Bitcoin Whitepaper" in meta.get("source_title", "") or "Ethereum Whitepaper" in meta.get("source_title", "")


def test_narration_path_also_generates_title(env, monkeypatch):
    """Narration format also generates a descriptive title."""
    store = env
    job_id = "test-narration-title"
    store.create(job_id, "https://example.com/article", style="balanced", fmt="narration")

    # For narration same-language, zero LLM calls for script; title generation is the only call
    generated_title = "AI safety: alignment and governance challenges"

    async def mock_chat_completion(prov, prompt, max_tokens=4096):
        # This is the title generation call (no translation call for same-lang narration)
        assert "Source title(s): Test Title" in prompt
        return generated_title

    def mock_llm_chain():
        return [{"name": "local", "base": "http://localhost:30001/v1", "model": "qwen3.6-35b"}]
    monkeypatch.setattr(pipeline, "_chat_completion", mock_chat_completion)
    monkeypatch.setattr(pipeline, "llm_chain", mock_llm_chain)

    _run(store, job_id)

    job = store.get(job_id)
    assert job["state"] == "done", job.get("error")
    assert job["title"] == generated_title


def test_title_generation_validates_length_bounds(env, monkeypatch):
    """Title must be 8-90 characters after stripping quotes and taking first line."""
    store = env
    job_id = "test-title-bounds"
    store.create(job_id, "https://example.com/article", style="balanced", fmt="dialog")

    script_content = '[{"speaker":"A","text":"Content one."},{"speaker":"B","text":"Content two."},{"speaker":"A","text":"Content three."},{"speaker":"B","text":"Content four."}]\nDESCRIPTION: test'

    # Test exactly 8 chars (min)
    async def mock_min(prov, prompt, max_tokens=4096):
        return "12345678"
    monkeypatch.setattr(pipeline, "script_call", _script_result(script_content, ""))
    monkeypatch.setattr(pipeline, "_chat_completion", mock_min)

    _run(store, job_id)
    job = store.get(job_id)
    assert job["title"] == "12345678"

    # Test exactly 90 chars (max)
    store2 = env
    job_id2 = "test-title-bounds2"
    store2.create(job_id2, "https://example.com/article2", style="balanced", fmt="dialog")

    async def mock_max(prov, prompt, max_tokens=4096):
        return "x" * 90

    with pytest.MonkeyPatch.context() as monkeypatch2:  # a bare MonkeyPatch() leaked into later tests
        monkeypatch2.setattr(pipeline, "script_call", _script_result(script_content, ""))
        monkeypatch2.setattr(pipeline, "_chat_completion", mock_max)
        _run(store2, job_id2)
    job2 = store2.get(job_id2)
    assert job2["title"] == "x" * 90