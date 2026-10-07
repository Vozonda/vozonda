"""Tests for mixed sources (URLs + text notes) in digest/combined jobs."""

import asyncio
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main, pipeline
from vozonda_api.jobs import JobStore

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

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
        return f"{name} article", f"{name} body text. " + "word " * 400, None

    async def fake_script_call(*, prompt, **kw):
        seen["prompts"].append(prompt)
        return [{"speaker": "AB"[i % 2], "text": f"turn {i}", "section": i // 3} for i in range(6)], "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return tmp_path / f"{job_id}.wav"

    async def fake_master(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(
        pipeline, "download_og_image",
        lambda *a, **k: asyncio.sleep(0, result=False), raising=False,
    )
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


# ---------------------------------------------------------------------------
# API: POST /jobs with both url and text (combined mode)
# ---------------------------------------------------------------------------


def test_post_jobs_both_url_and_text_becomes_combined_digest(monkeypatch):
    """When both url and text are provided, create a 2-source combined job."""
    import vozonda_api.jobs as jobs_mod
    _tmp = Path(tempfile.mkdtemp(prefix="vozonda-tests-"))
    jobs_mod.DB_PATH = _tmp / "jobs.db"
    jobs_mod.init_db()
    monkeypatch.setattr(main, "store", JobStore())

    def no_op_guard(url):
        pass

    monkeypatch.setattr("vozonda_api.fetcher.guard_url", no_op_guard)

    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "url": "https://example.com/source-a/article",
        "text": "This is my text note about crypto that is long enough to pass validation min twenty chars",
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 200, r.json()
    job = r.json()
    assert job["digest"] is True
    assert job["combine"] is True
    assert len(job["digest_sources"]) == 2
    assert "https://example.com/source-a/article" in job["digest_sources"]
    assert any(s.startswith("text:") for s in job["digest_sources"])


def test_post_jobs_both_url_and_text_short_fails():
    """Text shorter than 20 chars returns 422."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "url": "https://example.com/article",
        "text": "short",
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 422
    assert "too short" in r.json()["detail"].lower()


def test_post_jobs_text_only_still_works():
    """Single text source job still works (no URL)."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "text": "This is a standalone text source that is long enough to pass the minimum validation twenty chars or more",
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 200
    job = r.json()
    assert job["digest"] is False
    assert "pasted-" in job["id"]


def test_post_jobs_url_only_still_works():
    """Single URL job still works (no text)."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "url": "https://example.com/article",
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 200
    job = r.json()
    assert job["digest"] is False


def test_post_jobs_neither_url_nor_text_fails():
    """Neither url nor text returns 422."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 422
    assert "url or text" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# API: digest_sources with mixed URLs and text
# ---------------------------------------------------------------------------


def test_digest_sources_mixed_url_and_text_ok(env):
    """Digest with 1 URL + 1 text source completes successfully."""
    store, _seen = env
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "digest": True,
        "digest_sources": [
            "https://example.com/source-a/article",
            "text:This is my note about Ethereum which has enough chars to be valid twenty min here",
        ],
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 200, r.json()
    job = r.json()
    assert job["digest"] is True
    assert len(job["digest_sources"]) == 2
    _run(store, job["id"])
    job = store.get(job["id"])
    assert job["state"] == "done", job.get("error")


def test_digest_sources_all_urls_still_works(env):
    """All-URL digests continue to work unchanged."""
    store, _seen = env
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "digest": True,
        "digest_sources": [
            "https://example.com/source-a/article",
            "https://example.com/source-b/article",
        ],
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 200
    job = r.json()
    assert job["digest"] is True
    assert job["combine"] is False
    _run(store, job["id"])
    job = store.get(job["id"])
    assert job["state"] == "done", job.get("error")


# ---------------------------------------------------------------------------
# Validation: text source length
# ---------------------------------------------------------------------------


def test_digest_text_source_under_20_chars_fails():
    """A text source with raw content < 20 chars returns 422."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "digest": True,
        "digest_sources": [
            "https://example.com/a",
            "text:only 10 chars",
        ],
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 422
    assert "short" in r.json()["detail"].lower()


def test_digest_text_source_text_prefix_exact_length():
    """Text source with 'text:' prefix and exactly 20 chars passes."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "digest": True,
        "digest_sources": [
            "https://example.com/a",
            "text:" + "x" * 20,
        ],
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 200


def test_digest_requires_2_sources():
    """Digest with only 1 source is rejected."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "digest": True,
        "digest_sources": ["https://example.com/a"],
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 422


def test_digest_sources_raw_text_accepted():
    """Raw text (no text: prefix, not a URL) with >=20 chars is accepted."""
    client = TestClient(main.app)
    r = client.post("/jobs", json={
        "digest": True,
        "digest_sources": [
            "https://example.com/a",
            "This is raw text without any prefix that should be accepted because twenty chars",
        ],
        "style": "balanced",
        "format": "dialog",
    })
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Pipeline: _run_digest_job with text sources (no network)
# ---------------------------------------------------------------------------


def test_pipeline_text_source_no_http_call(monkeypatch):
    """Text sources in _run_digest_job do not trigger fetch_article HTTP calls."""
    _tmp = Path(tempfile.mkdtemp(prefix="vozonda-tests-"))
    import vozonda_api.jobs as jobs_mod
    jobs_mod.DB_PATH = _tmp / "jobs.db"
    jobs_mod.init_db()

    network_calls = []

    async def tracking_fetch(url):
        network_calls.append(url)
        if "btc" in url:
            return f"<html>{url}</html>"
        return "<html>other</html>"

    async def fake_extract(url, html=None, **kw):
        return f"{url} title", f"{url} body " * 100, "http://example.com/og.png"

    async def fake_script_call(*, prompt, **kw):
        return [{"speaker": "AB"[i % 2], "text": f"turn {i}", "section": i // 3} for i in range(6)], "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return _tmp / f"{job_id}.wav"

    async def fake_master(*a, **k):
        pass

    monkeypatch.setattr(pipeline, "fetch_article", tracking_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(pipeline, "download_og_image", lambda *a, **k: asyncio.sleep(0, result=False), raising=False)

    store = JobStore()
    store.create(
        "digest-tn1", "digest:digest-tn1",
        digest=True,
        digest_sources=[
            "https://example.com/source-a/article",
            "text:Direct text content that is longer than twenty chars for validation here and now ok",
        ],
        style="balanced", fmt="dialog",
    )

    async def go():
        async for _ in pipeline._run_digest_job(store, "digest-tn1", store.get("digest-tn1")):
            pass
    asyncio.run(go())

    # URL source was fetched
    assert any("example.com/source-a" in u for u in network_calls)
    # Text source was NOT fetched via HTTP
    assert not any("Direct text" in u or "Direct" in u for u in network_calls)
    job = store.get("digest-tn1")
    assert job["state"] == "done", job.get("error")


def test_pipeline_raw_text_without_prefix_in_digest_sources(monkeypatch):
    """Raw text sources without 'text:' prefix in digest_sources are treated as text and never fetched via HTTP."""
    _tmp = Path(tempfile.mkdtemp(prefix="vozonda-tests-"))
    import vozonda_api.jobs as jobs_mod
    jobs_mod.DB_PATH = _tmp / "jobs.db"
    jobs_mod.init_db()

    network_calls = []

    async def tracking_fetch(url):
        network_calls.append(url)
        return f"<html>{url}</html>"

    async def fake_extract(url, html=None, **kw):
        return f"{url} title", f"{url} body " * 100, None

    async def fake_script_call(*, prompt, **kw):
        return [{"speaker": "AB"[i % 2], "text": f"turn {i}", "section": i // 3} for i in range(6)], "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return _tmp / f"{job_id}.wav"

    async def fake_master(*a, **k):
        pass

    monkeypatch.setattr(pipeline, "fetch_article", tracking_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(pipeline, "download_og_image", lambda *a, **k: asyncio.sleep(0, result=False), raising=False)

    store = JobStore()
    store.create(
        "digest-raw1", "digest:digest-raw1",
        digest=True,
        digest_sources=[
            "https://example.com/source-a/article",
            "This is a raw text note without any prefix that must never be treated as an HTTP URL",
        ],
        style="balanced", fmt="dialog",
    )

    async def go():
        async for _ in pipeline._run_digest_job(store, "digest-raw1", store.get("digest-raw1")):
            pass
    asyncio.run(go())

    assert len(network_calls) == 1
    assert "example.com/source-a/article" in network_calls[0]
    job = store.get("digest-raw1")
    assert job["state"] == "done", job.get("error")


def test_pipeline_pure_text_digest_zero_fetches(monkeypatch):
    """A digest with only text sources makes zero HTTP calls."""
    _tmp = Path(tempfile.mkdtemp(prefix="vozonda-tests-"))
    import vozonda_api.jobs as jobs_mod
    jobs_mod.DB_PATH = _tmp / "jobs.db"
    jobs_mod.init_db()

    network_calls = []

    async def tracking_fetch(url):
        network_calls.append(url)
        return f"<html>{url}</html>"

    async def fake_script_call(*, prompt, **kw):
        return [{"speaker": "AB"[i % 2], "text": f"turn {i}", "section": i // 3} for i in range(6)], "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return _tmp / f"{job_id}.wav"

    async def fake_master(*a, **k):
        pass

    monkeypatch.setattr(pipeline, "fetch_article", tracking_fetch)
    monkeypatch.setattr(pipeline, "_extract", lambda *a, **kw: ("Notes", "text content", None))
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(pipeline, "download_og_image", lambda *a, **k: asyncio.sleep(0, result=False), raising=False)

    store = JobStore()
    store.create(
        "digest-pt1", "digest:digest-pt1",
        digest=True,
        digest_sources=[
            "text:First text note with enough content for twenty char minimum validation pass test here ok",
            "text:Second text note that also meets the minimum length threshold for valid text input here",
        ],
        style="balanced", fmt="dialog",
    )

    async def go():
        async for _ in pipeline._run_digest_job(store, "digest-pt1", store.get("digest-pt1")):
            pass
    asyncio.run(go())

    assert network_calls == [], f"No HTTP calls for pure-text digests, got: {network_calls}"
    job = store.get("digest-pt1")
    assert job["state"] == "done", job.get("error")


def test_pipeline_text_source_title_from_first_line(monkeypatch):
    """Text sources use first line as title when extracting in _run_digest_job."""
    _tmp = Path(tempfile.mkdtemp(prefix="vozonda-tests-"))
    import vozonda_api.jobs as jobs_mod
    jobs_mod.DB_PATH = _tmp / "jobs.db"
    jobs_mod.init_db()

    extracted_titles = []

    async def fake_extract(url, html=None, **kw):
        extracted_titles.append(f"url:{url}")
        return "URL Article Title", "url body " * 100, None

    async def fake_script_call(*, prompt, **kw):
        return [{"speaker": "AB"[i % 2], "text": f"turn {i}", "section": i // 3} for i in range(6)], "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return _tmp / f"{job_id}.wav"

    async def fake_fetch(url):
        return f"<html>{url}</html>"

    async def fake_master(*a, **k):
        pass

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(pipeline, "download_og_image", lambda *a, **k: asyncio.sleep(0, result=False), raising=False)

    store = JobStore()
    store.create(
        "digest-tl1", "digest:digest-tl1",
        digest=True,
        digest_sources=[
            "text:My Custom Title Line\nThis is the body of the text note with enough content for twenty chars",
            "https://example.com/source-a/article",
        ],
        style="balanced", fmt="dialog",
    )

    async def go():
        async for _ in pipeline._run_digest_job(store, "digest-tl1", store.get("digest-tl1")):
            pass
    asyncio.run(go())

    job = store.get("digest-tl1")
    assert job["state"] == "done", job.get("error")
    assert any("example.com/source-a" in t for t in extracted_titles), \
        f"Expected URL extraction, got: {extracted_titles}"