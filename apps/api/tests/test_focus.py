"""Listener focus (UX phase 2): stored with the job, sent to the script LLM as a
priority block that forbids inventing facts, empty focus changes nothing."""

import asyncio

from fastapi.testclient import TestClient

from vozonda_api import main, pipeline
from vozonda_api.jobs import FOCUS_MAX


def test_focus_block_rules_and_limits():
    assert pipeline._focus_block(None) == ""
    assert pipeline._focus_block("   ") == ""
    block = pipeline._focus_block("the privacy angle,\n skip the history")
    assert "the privacy angle, skip the history" in block
    assert "never invent facts" in block
    assert len(pipeline._focus_block("x" * 5000)) < 300 + 400


def test_focus_is_stored_with_the_job(monkeypatch):
    async def fake_run_job(store, job_id):
        yield store.get(job_id)

    monkeypatch.setattr(main, "run_job", fake_run_job)
    body = {"url": "https://example.com/a", "focus": "  what changed in 2026  " + "y" * 600}
    job = TestClient(main.app).post("/jobs", json=body).json()
    stored = main.store.get(job["id"])["focus"]
    assert stored.startswith("what changed in 2026")
    assert len(stored) == FOCUS_MAX


def test_focus_reaches_the_script_prompt(monkeypatch):
    seen = {}

    async def fake_script_call(*, prompt, **kw):
        seen["prompt"] = prompt
        return [{"speaker": "AB"[i % 2], "text": f"line {i}"} for i in range(6)], "desc"

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    asyncio.run(pipeline._script("Some source text about Nostr relays.", focus="the privacy angle"))
    assert "LISTENER FOCUS" in seen["prompt"] and "the privacy angle" in seen["prompt"]

    seen.clear()
    asyncio.run(pipeline._script("Some source text about Nostr relays."))
    assert "LISTENER FOCUS" not in seen["prompt"]
