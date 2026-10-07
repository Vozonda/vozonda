"""Multi-source episodes cite per line: missing `src` is repaired once, and a
reviewed script keeps (and validates) it."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main, pipeline
from vozonda_api.jobs import JobStore

LONG = "this content turn says quite a few things drawn from the sources"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import vozonda_api.doctor as doc
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(doc, "blocking_problem", lambda: None)
    seen: dict = {"repair": []}

    async def fake_fetch(url):
        return f"<html>{url}</html>"

    async def fake_extract(url, html=None, **kw):
        return f"{url} title", "text. " + "word " * 400, None

    async def fake_script_call(*, prompt, **kw):
        # the model omits src on every turn
        return [{"speaker": "AB"[i % 2], "text": f"{LONG} {i}"} for i in range(6)], "desc"

    async def fake_chat(prov, prompt, max_tokens=4096):
        if "numbered script turn" not in prompt:
            return "A Title"
        seen["repair"].append(prompt)
        return 'sure: [{"i":0,"src":[2,1]},{"i":1,"src":[9]},{"i":2,"src":[2]},{"i":3,"src":[1]}]'

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return tmp_path / f"{job_id}.wav"

    async def fake_master(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    return JobStore(), seen


def _drain(store, job_id):
    async def go():
        async for _ in pipeline.run_job(store, job_id):
            pass
    asyncio.run(go())


def _combine(store, job_id, **kw):
    store.create(job_id, f"digest:{job_id}", digest=True, combine=True,
                 digest_sources=["https://a.example/1", "https://b.example/2"], **kw)


def test_missing_src_is_repaired_and_stored(env):
    store, seen = env
    _combine(store, "src-1")
    _drain(store, "src-1")
    job = store.get("src-1")
    assert job["state"] == "done"
    assert len(seen["repair"]) == 1
    srcs = [ln.get("src") for ln in job["script"]]
    # out-of-range answer dropped, unanswered turns stay uncited, no text changed
    assert srcs[:4] == [[1, 2], None, [2], [1]]
    assert all(ln["text"].startswith(LONG) for ln in job["script"] if ln["text"].startswith(LONG))


def test_prompt_makes_src_required(env, monkeypatch):
    store, _ = env
    prompts = []
    orig = pipeline.script_call

    async def spy(*, prompt, **kw):
        prompts.append(prompt)
        return await orig(prompt=prompt, **kw)

    monkeypatch.setattr(pipeline, "script_call", spy)
    _combine(store, "src-2")
    _drain(store, "src-2")
    assert "MUST carry" in prompts[-1]


def test_single_source_needs_no_repair(env):
    store, seen = env
    store.create("src-3", "https://a.example/1")
    _drain(store, "src-3")
    assert seen["repair"] == []


def test_review_keeps_src_and_drops_out_of_range(env, monkeypatch):
    store, _ = env

    async def fake_run(job_id, runner=None):
        return None

    monkeypatch.setattr(main, "_run", fake_run)
    monkeypatch.setattr(main, "store", store)
    _combine(store, "src-4", review_script=True)
    _drain(store, "src-4")
    assert store.get("src-4")["state"] == "awaiting_review"
    client = TestClient(main.app)
    lines = [
        {"speaker": "A", "text": "one", "src": [2, 1, 1]},
        {"speaker": "B", "text": "two", "src": [0, 3, "x"]},
        {"speaker": "A", "text": "three"},
    ]
    assert client.post("/jobs/src-4/script", json={"lines": lines}).status_code == 200
    assert store.get("src-4")["script"] == [
        {"speaker": "A", "text": "one", "src": [1, 2]},
        {"speaker": "B", "text": "two"},
        {"speaker": "A", "text": "three"},
    ]
