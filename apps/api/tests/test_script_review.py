"""Script review (UX phase 2): pause after the script, edit, then voice exactly
the reviewed script through the same tail as an unreviewed job."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main, pipeline
from vozonda_api.jobs import JobStore

TEXT = ("Nostr is a simple open protocol for censorship resistant social media. " * 12).strip()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import vozonda_api.doctor as doc
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(doc, "blocking_problem", lambda: None)
    voiced: dict = {}

    async def fake_script_call(*, prompt, **kw):
        return [{"speaker": "A" if i % 2 == 0 else "B", "text": f"original line {i}"} for i in range(6)], "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        voiced["lines"] = [dict(ln) for ln in lines]
        return tmp_path / f"{job_id}.wav"

    async def fake_master(*a, **k):
        return tmp_path / "out.mp3"

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    return JobStore(), voiced


def _drain(gen):
    async def run():
        states = []
        async for s in gen:
            states.append(s["state"])
        return states
    return asyncio.run(run())


def test_review_pauses_after_the_script_without_voicing(env):
    store, voiced = env
    store.create("rv-1", TEXT, review_script=True)
    states = _drain(pipeline.run_job(store, "rv-1"))
    job = store.get("rv-1")
    assert job["state"] == "awaiting_review" and states[-1] == "awaiting_review"
    assert len(job["script"]) == 6 and "lines" not in voiced


def test_without_review_the_job_runs_through(env):
    store, voiced = env
    store.create("rv-2", TEXT)
    _drain(pipeline.run_job(store, "rv-2"))
    assert store.get("rv-2")["state"] == "done"
    assert voiced["lines"][0]["text"] == "original line 0"


def test_resume_voices_the_edited_script(env):
    store, voiced = env
    store.create("rv-3", TEXT, review_script=True)
    _drain(pipeline.run_job(store, "rv-3"))
    store.update("rv-3", script=[{"speaker": "A", "text": "edited one"}, {"speaker": "B", "text": "edited two"}],
                 script_approved=True)
    _drain(pipeline.resume_after_review(store, "rv-3"))
    assert store.get("rv-3")["state"] == "done"
    assert [ln["text"] for ln in voiced["lines"]] == ["edited one", "edited two"]


def test_approve_endpoint_validates_and_resumes(env, monkeypatch):
    store, _ = env
    started = {}

    async def fake_run(job_id, runner=None):
        started[job_id] = runner

    monkeypatch.setattr(main, "_run", fake_run)
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    store.create("rv-4", TEXT, review_script=True)
    assert client.post("/jobs/rv-4/script", json={}).status_code == 409  # not paused yet
    _drain(pipeline.run_job(store, "rv-4"))
    bad = client.post("/jobs/rv-4/script", json={"lines": [{"speaker": "Z", "text": "x"}]})
    assert bad.status_code == 422
    empty = client.post("/jobs/rv-4/script", json={"lines": [{"speaker": "A", "text": "  "}]})
    assert empty.status_code == 422
    ok = client.post("/jobs/rv-4/script", json={"lines": [{"speaker": "A", "text": " fixed   text "}]})
    assert ok.status_code == 200 and ok.json()["state"] == "queued"
    assert store.get("rv-4")["script"] == [{"speaker": "A", "text": "fixed text"}]
    assert started.get("rv-4") is pipeline.resume_after_review


def test_digest_rejects_review():
    body = {"digest": True, "digest_sources": ["https://a.example/x", "https://b.example/y"], "review_script": True}
    assert TestClient(main.app).post("/jobs", json=body).status_code == 422


def test_approve_with_new_title_stores_it(env, monkeypatch):
    store, _ = env
    started = {}

    async def fake_run(job_id, runner=None):
        started[job_id] = runner

    monkeypatch.setattr(main, "_run", fake_run)
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    store.create("rv-5", TEXT, review_script=True)
    _drain(pipeline.run_job(store, "rv-5"))
    # approve with a new title
    resp = client.post("/jobs/rv-5/script", json={"title": "  My New Episode Title  "})
    assert resp.status_code == 200
    job = store.get("rv-5")
    assert job["title"] == "My New Episode Title"
    # stage meta should have title_edited
    script_stage = next(s for s in job["stages"] if s["name"] == "script")
    assert script_stage["meta"].get("title_edited") is True


def test_approve_empty_title_returns_422(env, monkeypatch):
    store, _ = env
    started = {}

    async def fake_run(job_id, runner=None):
        started[job_id] = runner

    monkeypatch.setattr(main, "_run", fake_run)
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    store.create("rv-6", TEXT, review_script=True)
    _drain(pipeline.run_job(store, "rv-6"))
    before = store.get("rv-6")["title"]
    # empty title
    resp = client.post("/jobs/rv-6/script", json={"title": "   "})
    assert resp.status_code == 422
    # a rejected title leaves the job title as it was
    assert store.get("rv-6")["title"] == before


def test_approve_title_too_long_returns_422(env, monkeypatch):
    store, _ = env
    started = {}

    async def fake_run(job_id, runner=None):
        started[job_id] = runner

    monkeypatch.setattr(main, "_run", fake_run)
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    store.create("rv-7", TEXT, review_script=True)
    _drain(pipeline.run_job(store, "rv-7"))
    before = store.get("rv-7")["title"]
    # title too long (>120 chars)
    resp = client.post("/jobs/rv-7/script", json={"title": "x" * 121})
    assert resp.status_code == 422
    assert store.get("rv-7")["title"] == before


def test_approve_without_title_keeps_old_one(env, monkeypatch):
    store, _ = env
    started = {}

    async def fake_run(job_id, runner=None):
        started[job_id] = runner

    monkeypatch.setattr(main, "_run", fake_run)
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    store.create("rv-8", TEXT, review_script=True)
    _drain(pipeline.run_job(store, "rv-8"))
    original_title = store.get("rv-8")["title"]
    # approve without title (only lines)
    resp = client.post("/jobs/rv-8/script", json={"lines": [{"speaker": "A", "text": "edited"}]})
    assert resp.status_code == 200
    job = store.get("rv-8")
    assert job["title"] == original_title
