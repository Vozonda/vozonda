"""Need-based budget split and main/context roles (VOZONDA-TRAY-ALLOCATION)."""

import asyncio

import pytest

from vozonda_api import pipeline
from vozonda_api.budget import allocate
from vozonda_api.jobs import JobStore


def test_long_paper_gets_what_short_notes_do_not_need():
    shares = allocate([50000, 500, 500], ["main", "main", "main"], 10000)
    assert shares[1] == 500
    assert shares[2] == 500
    assert shares[0] == 9000
    assert sum(shares) <= 10000


def test_all_short_sources_keep_everything():
    shares = allocate([1000, 2000, 700], ["main", "main", "main"], 10000)
    assert shares == [1000, 2000, 700]


def test_context_gets_its_floor_before_mains():
    shares = allocate([50000, 5000], ["main", "context"], 10000)
    assert shares[1] == 3000
    assert shares[0] == 7000


def test_surplus_flows_to_context_last():
    shares = allocate([1000, 50000], ["main", "context"], 10000)
    assert shares[0] == 1000
    assert shares[1] == 9000
    assert sum(shares) <= 10000


def test_sum_never_exceeds_budget_and_never_over_length():
    shares = allocate([8000, 8000, 8000], ["main", "main", "context"], 10000)
    assert sum(shares) <= 10000
    for kept, total in zip(shares, [8000, 8000, 8000]):
        assert kept <= total


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import vozonda_api.doctor as doc
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(doc, "blocking_problem", lambda: None)
    seen: dict = {"prompts": []}

    async def fake_fetch(url):
        return f"<html>{url}</html>"

    async def fake_extract(url, html=None):
        name = "MainPaper" if "main-paper" in url else "OtherPaper"
        return f"{name} title", f"{name} body. " + "word " * 2000, None

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


def _run_digest(store, job_id, budget_chars=None):
    async def go():
        job = store.get(job_id)
        async for _ in pipeline._run_digest_job(store, job_id, job, budget_chars):
            pass
    asyncio.run(go())


def test_combined_digest_puts_context_under_background_heading(env):
    from vozonda_api import sources as sources_mod

    store, seen = env
    store.create(
        "digest-alloc1", "digest:digest-alloc1",
        digest=True, combine=True,
        digest_sources=[
            "https://example.com/main-paper/article",
            "text:Context note\n" + "background detail " * 400,
        ],
        style="balanced", fmt="dialog",
    )
    sources_mod.save_job_sources("digest-alloc1", [
        {"id": None, "kind": "article", "title": "MainPaper title", "origin_url": "https://example.com/main-paper/article",
         "role": "main", "text": "MainPaper body. " + "word " * 2000},
        {"id": None, "kind": "note", "title": "Context note", "origin_url": None,
         "role": "context", "text": "Context note\n" + "background detail " * 400},
    ])
    _run_digest(store, "digest-alloc1", budget_chars=8000)
    job = store.get("digest-alloc1")
    assert job["state"] == "done", job.get("error")
    prompt = seen["prompts"][-1]
    assert "ONE conversation" in prompt
    assert "BACKGROUND" in prompt
    assert "MAIN MATERIAL" in prompt
    bg = prompt.index("BACKGROUND")
    assert "Context note" in prompt[bg:]
    main_at = prompt.index("MAIN MATERIAL")
    assert "MainPaper title" in prompt[main_at:bg]


def test_legacy_digest_without_job_sources_still_works(env):
    store, seen = env
    store.create(
        "digest-legacy1", "digest:digest-legacy1",
        digest=True, combine=True,
        digest_sources=[
            "https://example.com/main-paper/article",
            "text:Legacy note\n" + "legacy words " * 200,
        ],
        style="balanced", fmt="dialog",
    )
    _run_digest(store, "digest-legacy1", budget_chars=20000)
    job = store.get("digest-legacy1")
    assert job["state"] == "done", job.get("error")
    assert "ONE conversation" in seen["prompts"][-1]


def test_oversized_source_is_cut_and_recorded_as_truncated(env):
    store, seen = env
    store.create(
        "digest-trunc1", "digest:digest-trunc1",
        digest=True,
        digest_sources=[
            "https://example.com/main-paper/article",
            "https://example.com/other/article",
        ],
        style="balanced", fmt="dialog",
    )
    _run_digest(store, "digest-trunc1", budget_chars=8000)
    job = store.get("digest-trunc1")
    assert job["state"] == "done", job.get("error")
    stages = {s["name"]: s for s in job.get("stages", [])}
    truncated = (stages.get("extract", {}).get("meta", {}) or {}).get("truncated", [])
    assert truncated, "expected truncated meta on the extract stage"
    for entry in truncated:
        assert set(entry) == {"position", "kept", "total"}
        assert entry["kept"] < entry["total"]
