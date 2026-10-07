"""2+ sources from compose become ONE conversation (combine); the per-source
digest stays the default for other callers (watchlists) and the explicit show."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main, pipeline
from vozonda_api.jobs import JobStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import vozonda_api.doctor as doc
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(doc, "blocking_problem", lambda: None)
    seen: dict = {"prompts": []}

    async def fake_fetch(url):
        return f"<html>{url}</html>"

    async def fake_extract(url, html=None, **kw):
        name = "Bitcoin" if "btc" in url else "Ethereum"
        return f"{name} whitepaper", f"{name} text. " + "word " * 400, None

    async def fake_script_call(*, prompt, **kw):
        seen["prompts"].append(prompt)
        return [{"speaker": "AB"[i % 2], "text": f"turn {i}", "section": i // 3} for i in range(6)], "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return tmp_path / f"{job_id}.wav"

    async def fake_master(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "download_og_image", lambda *a, **k: asyncio.sleep(0, result=False), raising=False)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    return JobStore(), seen


def _run(store, job_id):
    async def go():
        async for _ in pipeline.run_job(store, job_id):
            pass
    asyncio.run(go())


def test_combine_writes_one_conversation_across_sources(env):
    store, seen = env
    store.create("digest-c1", "digest:digest-c1", digest=True,
                 digest_sources=["https://btc.example/wp", "https://eth.example/wp"], combine=True)
    _run(store, "digest-c1")
    job = store.get("digest-c1")
    assert job["state"] == "done", job.get("error")
    prompt = seen["prompts"][-1]
    assert "ONE conversation" in prompt and "SOURCE 1 of 2" in prompt and "SOURCE 2 of 2" in prompt
    assert "DIGEST episode" not in prompt


def test_without_combine_it_stays_a_digest(env):
    store, seen = env
    store.create("digest-d1", "digest:digest-d1", digest=True,
                 digest_sources=["https://btc.example/wp", "https://eth.example/wp"])
    _run(store, "digest-d1")
    assert "DIGEST episode" in seen["prompts"][-1]


def test_review_is_allowed_for_combine_but_not_for_a_digest():
    base = {"digest": True, "digest_sources": ["https://a.example/x", "https://b.example/y"], "review_script": True}
    client = TestClient(main.app)
    assert client.post("/jobs", json=base).status_code == 422
