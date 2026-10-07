"""Tray privacy (VOZONDA-TRAY-PRIVACY, docs/plan-multisource-tray.md sections 2 and 3).

An episode whose tray holds an uploaded file is written by the local model
unless the tray allowed the cloud for this episode (allow_cloud_for_uploads).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main
from vozonda_api import providers as P
from vozonda_api import settings_store as ss
from vozonda_api import sources as S
from vozonda_api.jobs import JobStore
from vozonda_api.pipeline import NO_LOCAL_MODEL_MSG, run_job

NOTE = "A background note\nThe grid runs on one DGX Spark at home, ready to go."


@pytest.fixture
def api(jobs_db, monkeypatch):
    S.init_sources_db()
    monkeypatch.setattr(main, "store", JobStore())

    async def no_run(job_id, runner=None):
        return None

    monkeypatch.setattr(main, "_run", no_run)
    return TestClient(main.app)


def _uploaded_pdf():
    sid = S._insert("file", None)
    S._set_ready(sid, "pdf", "Quarterly numbers", "Confidential revenue text that is long enough to be stored.")
    return S.get(sid)


def _note():
    return S.add_note(NOTE)


def _link():
    sid = S._insert("article", "https://news.example/a")
    S._set_ready(sid, "article", "A story", "Some article text that is long enough to count here.")
    return S.get(sid)


def test_uploaded_pdf_makes_the_job_local_only(api):
    r = api.post("/jobs", json={"sources": [{"id": _uploaded_pdf()["id"]}]})
    assert r.status_code == 200, r.text
    assert r.json()["local_only"] is True
    assert main.store.get(r.json()["id"])["local_only"] is True


def test_allow_cloud_for_uploads_keeps_the_job_cloud_eligible(api):
    r = api.post("/jobs", json={"sources": [{"id": _uploaded_pdf()["id"]}], "allow_cloud_for_uploads": True})
    assert r.status_code == 200, r.text
    assert r.json()["local_only"] is False


def test_links_and_notes_stay_cloud_eligible(api):
    body = {"sources": [{"id": _link()["id"]}, {"id": _note()["id"], "role": "context"}]}
    r = api.post("/jobs", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["local_only"] is False


@pytest.fixture
def cloud_engine(monkeypatch):
    """Script engine kimi_nim with a local backup; restores the settings after."""
    monkeypatch.setenv("VOZONDA_NIM_MODEL", "moonshotai/kimi-k3")
    old = {k: ss.get_setting(k) for k in ("llm.engine", "llm.backup_engine", "llm.nim_model")}
    ss.set_setting("llm.engine", "kimi_nim")
    ss.set_setting("llm.backup_engine", "local")
    ss.set_setting("llm.nim_model", "moonshotai/kimi-k3")
    yield
    fallback = {"llm.engine": "local", "llm.backup_engine": "", "llm.nim_model": ""}
    for k, v in old.items():
        ss.set_setting(k, v if v is not None else fallback[k])


def test_local_only_chain_drops_the_cloud_provider(cloud_engine):
    assert P.LOCAL_ONLY.get() is False
    full = P.llm_chain()
    assert full and full[0]["name"] == "kimi_nim"
    assert any(p["name"] == "local" for p in full[1:])
    token = P.LOCAL_ONLY.set(True)
    try:
        narrowed = P.llm_chain()
    finally:
        P.LOCAL_ONLY.reset(token)
    assert narrowed and all(P.is_local_provider(p) for p in narrowed)
    assert [p["name"] for p in narrowed] == ["local"]
    assert P.LOCAL_ONLY.get() is False


def test_local_only_job_fails_without_a_local_provider(jobs_db, cloud_engine, monkeypatch):
    import vozonda_api.doctor as doc

    monkeypatch.setattr(doc, "blocking_problem", lambda: None)
    ss.set_setting("llm.backup_engine", "none")
    store = JobStore()
    store.create("priv-nolocal", "Some pasted text that is long enough to be read aloud.", local_only=True)

    async def drain():
        async for _ in run_job(store, "priv-nolocal"):
            pass

    asyncio.run(drain())
    job = store.get("priv-nolocal")
    assert job["state"] == "failed"
    assert job["error"] == NO_LOCAL_MODEL_MSG
    assert P.LOCAL_ONLY.get() is False


def test_meta_reports_whether_the_script_engine_is_local(api, cloud_engine):
    ss.set_setting("llm.engine", "local")
    assert api.get("/meta").json()["script_engine_local"] is True
    ss.set_setting("llm.engine", "kimi_nim")
    assert api.get("/meta").json()["script_engine_local"] is False
