"""Source objects for the source tray (VOZONDA-MULTI-SOURCE-TRAY): read on add, uploads
kept as text only, the per-job copy that variants and citations use."""

import asyncio
import io
import time

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main
from vozonda_api import sources as S
from vozonda_api.fetcher import FetchError
from vozonda_api.jobs import JobStore

NOTE = "My background note\nThe hosts should know that the grid runs on one DGX Spark at home."


@pytest.fixture
def env(jobs_db, monkeypatch):
    S.init_sources_db()
    monkeypatch.setattr(main, "store", JobStore())

    async def no_run(job_id, runner=None):
        return None

    monkeypatch.setattr(main, "_run", no_run)
    return TestClient(main.app)


def _ready_note(text=NOTE):
    return S.add_note(text)


def _await_reads():
    async def go():
        while S._tasks:
            await asyncio.gather(*list(S._tasks), return_exceptions=True)

    return go()


# --- reading ---------------------------------------------------------------


@pytest.mark.parametrize(
    "data,kind",
    [
        (b"%PDF-1.7\n...", "pdf"),
        (b"\x89PNG\r\n\x1a\n....", "png"),
        (b"\xff\xd8\xff\xe0....", "jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        ("# notes\nplain markdown, äöü".encode(), "text"),
        (b"\x00\x01\x02binary", None),
        (b"\xff\xfe\xfa not utf8", None),
    ],
)
def test_sniff_takes_the_type_from_the_bytes(data, kind):
    assert S.sniff(data) == kind


def test_a_note_is_ready_at_once_with_title_size_and_language(env):
    r = env.post("/sources", json={"text": NOTE})
    assert r.status_code == 202, r.text
    src = r.json()
    assert src["status"] == "ready" and src["kind"] == "note"
    assert src["title"] == "My background note"
    assert src["words"] == len(NOTE.split())
    assert "text" not in src and src["preview"].startswith("My background")


def test_a_too_short_note_is_refused_with_a_hint(env):
    r = env.post("/sources", json={"text": "too short"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "too_short"


def test_url_or_text_not_both(env):
    assert env.post("/sources", json={"url": "https://a.example/x", "text": NOTE}).status_code == 422
    assert env.post("/sources", json={}).status_code == 422


def test_a_local_address_fails_the_request_not_the_card(env):
    r = env.post("/sources", json={"url": "http://127.0.0.1:8787/jobs"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "blocked_address"


def test_a_link_is_read_in_the_background_and_gets_its_real_kind(jobs_db, monkeypatch):
    S.init_sources_db()
    monkeypatch.setattr(S, "guard_url", lambda u: None)

    async def fake_fetch(url):
        return "pdf", "Attention Is All You Need\n\n" + "The transformer uses attention. " * 50

    monkeypatch.setattr(S, "fetch_document", fake_fetch)

    async def go():
        src = S.add_url("https://arxiv.org/abs/1706.03762")  # no .pdf in the link
        assert src["status"] == "reading"
        await _await_reads()
        return S.get(src["id"], with_text=True)

    done = asyncio.run(go())
    assert done["status"] == "ready" and done["kind"] == "pdf"
    assert done["title"] == "Attention Is All You Need"
    assert done["origin_url"] == "https://arxiv.org/abs/1706.03762"
    assert done["language"] == "en"


@pytest.mark.parametrize(
    "exc,code,retryable",
    [
        (FetchError("fetch failed: HTTP 403"), "paywall", False),
        (FetchError("fetch failed: HTTP 404"), "unreachable", True),
        (FetchError("No subtitles available for this video"), "no_subtitles", False),
        (FetchError("could not extract text from PDF (empty or scanned without text layer)"), "pdf_no_text", False),
        (TimeoutError(), "timeout", True),
    ],
)
def test_a_failed_link_turns_red_with_a_next_step(jobs_db, monkeypatch, exc, code, retryable):
    S.init_sources_db()
    monkeypatch.setattr(S, "guard_url", lambda u: None)

    async def fake_fetch(url):
        raise exc

    monkeypatch.setattr(S, "fetch_document", fake_fetch)

    async def go():
        src = S.add_url("https://news.example/story")
        await _await_reads()
        return S.get(src["id"])

    failed = asyncio.run(go())
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == code
    assert failed["error"]["hint"] == S.ERRORS[code][0]
    assert failed["error"]["retryable"] is retryable


def test_retry_reads_a_failed_link_again(jobs_db, monkeypatch):
    S.init_sources_db()
    monkeypatch.setattr(S, "guard_url", lambda u: None)
    calls = []

    async def flaky(url):
        calls.append(url)
        if len(calls) == 1:
            raise FetchError("fetch failed: ReadTimeout timed out")
        return "youtube", "A talk about grids\n\n" + "we talk about power and latency " * 20

    monkeypatch.setattr(S, "fetch_document", flaky)

    async def go():
        src = S.add_url("https://youtu.be/abcdefghijk")
        await _await_reads()
        assert S.get(src["id"])["status"] == "failed"
        S.retry(src["id"])
        await _await_reads()
        return S.get(src["id"])

    again = asyncio.run(go())
    assert again["status"] == "ready" and again["kind"] == "youtube"
    assert again["title"] == "A talk about grids" and again["error"] is None


def test_an_upload_cannot_be_retried(jobs_db):
    S.init_sources_db()
    sid = S._insert("file", None)
    S._set_failed(sid, "unreadable")
    with pytest.raises(S.SourceError):
        S.retry(sid)


# --- uploads ---------------------------------------------------------------


def test_an_uploaded_pdf_keeps_only_its_text(jobs_db, monkeypatch):
    S.init_sources_db()
    seen = {}

    def fake_pdftotext(data):
        seen["bytes"] = data
        return "Grid Report 2026\nPower draw stayed under 240 W for the whole month of testing."

    monkeypatch.setattr(S, "_extract_pdf_text", fake_pdftotext)

    async def go():
        src = S.add_upload(b"%PDF-1.7 fake body")
        await _await_reads()
        return S.get(src["id"], with_text=True)

    done = asyncio.run(go())
    assert seen["bytes"].startswith(b"%PDF")
    assert done["status"] == "ready" and done["kind"] == "pdf"
    assert done["title"] == "Grid Report 2026"
    assert done["origin_url"] is None
    assert "Power draw" in done["text"]


def test_an_uploaded_image_is_downscaled_and_reencoded_before_vision(jobs_db, monkeypatch):
    from PIL import Image

    S.init_sources_db()
    buf = io.BytesIO()
    Image.new("RGB", (3000, 1200), "white").save(buf, format="PNG")
    seen = {}

    async def fake_vision(data, ctype):
        seen["ctype"] = ctype
        seen["size"] = Image.open(io.BytesIO(data)).size
        return "Slide title\nThe slide shows a chart of tokens per second over a week."

    monkeypatch.setattr(S, "_extract_image_text", fake_vision)

    async def go():
        src = S.add_upload(buf.getvalue())
        await _await_reads()
        return S.get(src["id"])

    done = asyncio.run(go())
    assert done["status"] == "ready" and done["kind"] == "image"
    assert seen["ctype"] == "image/jpeg"
    assert max(seen["size"]) == S.IMAGE_MAX_SIDE


def test_upload_endpoint_refuses_unknown_and_oversized_files(env, monkeypatch):
    r = env.post("/sources/upload", content=b"\x00\x01binary blob", headers={"content-type": "application/octet-stream"})
    assert r.status_code == 415 and r.json()["detail"]["code"] == "unsupported_type"
    monkeypatch.setattr(S, "UPLOAD_MAX_BYTES", 10)
    r = env.post("/sources/upload", content=b"%PDF-1.7 way more than ten bytes")
    assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
    assert env.post("/sources/upload", content=b"").status_code == 422


def test_rename_and_delete(env):
    sid = _ready_note()["id"]
    r = env.patch(f"/sources/{sid}", json={"title": "Private memo"})
    assert r.status_code == 200 and r.json()["title"] == "Private memo"
    assert env.delete(f"/sources/{sid}").status_code == 200
    assert env.get(f"/sources/{sid}").status_code == 404


# --- jobs ------------------------------------------------------------------


def test_a_tray_of_two_starts_one_job_and_keeps_a_copy(env):
    a = _ready_note()
    b = _ready_note("Second note title\nContext about the router and the 2.4 GHz channel setup.")
    r = env.post("/jobs", json={"sources": [{"id": a["id"]}, {"id": b["id"], "role": "context"}], "combine": True})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["digest"] is True and len(job["digest_sources"]) == 2
    assert job["digest_sources"][0] == "text:" + NOTE  # the title line is not doubled
    listed = env.get(f"/jobs/{job['id']}/sources").json()
    assert [s["role"] for s in listed] == ["main", "context"]
    assert listed[0]["title"] == "My background note"
    assert all("text" not in s for s in listed)


def test_one_link_keeps_the_url_path(env):
    sid = S._insert("article", "https://news.example/a")
    S._set_ready(sid, "article", "A story", "Some article text that is long enough to count.")
    job = env.post("/jobs", json={"sources": [{"id": sid}]}).json()
    assert job["url"] == "https://news.example/a"
    assert env.get(f"/jobs/{job['id']}/sources").json()[0]["origin_url"] == "https://news.example/a"


def test_an_uploaded_source_is_public_by_title_only(env):
    sid = S._insert("file", None)
    S._set_ready(sid, "pdf", "Quarterly numbers", "Confidential: revenue was 12 and costs were 9 this quarter.")
    job = env.post("/jobs", json={"sources": [{"id": sid}]}).json()
    listed = env.get(f"/jobs/{job['id']}/sources").json()
    assert listed == [{"position": 0, "kind": "pdf", "title": "Quarterly numbers", "origin_url": None, "role": "main", "words": 10}]


@pytest.mark.parametrize(
    "setup,status",
    [
        ("unknown", 404),
        ("reading", 409),
        ("failed", 422),
        ("context_only", 422),
        ("twice", 422),
        ("with_url", 422),
    ],
)
def test_a_tray_that_cannot_start(env, setup, status):
    note = _ready_note()["id"]
    body = {"sources": [{"id": note}]}
    if setup == "unknown":
        body = {"sources": [{"id": "src-doesnotexist"}]}
    elif setup == "reading":
        body = {"sources": [{"id": S._insert("article", "https://a.example/x")}]}
    elif setup == "failed":
        sid = S._insert("article", "https://a.example/x")
        S._set_failed(sid, "paywall")
        body = {"sources": [{"id": note}, {"id": sid}]}
    elif setup == "context_only":
        body = {"sources": [{"id": note, "role": "context"}]}
    elif setup == "twice":
        body = {"sources": [{"id": note}, {"id": note}]}
    elif setup == "with_url":
        body["url"] = "https://a.example/x"
    assert env.post("/jobs", json=body).status_code == status


def test_variant_clones_the_exact_text(env):
    a, b = _ready_note(), _ready_note("Other note\nAnother long enough piece of context for the hosts.")
    job = env.post("/jobs", json={"sources": [{"id": a["id"]}, {"id": b["id"], "role": "context"}]}).json()
    S.delete(a["id"])  # the tray sources may be long gone
    clones = env.post(f"/jobs/{job['id']}/sources/clone").json()
    assert [c["role"] for c in clones] == ["main", "context"]
    assert all(c["status"] == "ready" and c["id"] not in (a["id"], b["id"]) for c in clones)
    assert S.get(clones[0]["id"], with_text=True)["text"] == NOTE


def test_a_legacy_digest_lists_its_sources(env, monkeypatch):
    monkeypatch.setattr("vozonda_api.fetcher.guard_url", lambda u: None)
    job = env.post(
        "/jobs",
        json={"digest": True, "digest_sources": ["https://a.example/one", "text:" + NOTE]},
    ).json()
    listed = env.get(f"/jobs/{job['id']}/sources").json()
    assert listed[0]["origin_url"] == "https://a.example/one"
    assert listed[1]["kind"] == "note" and listed[1]["title"] == "My background note"


def test_unused_sources_expire_but_a_jobs_copy_stays(env):
    old, fresh = _ready_note(), _ready_note()
    job = env.post("/jobs", json={"sources": [{"id": old["id"]}]}).json()
    with S.jobs_mod._conn() as c:
        c.execute("UPDATE sources SET created_at = ? WHERE id = ?", (time.time() - S.SOURCE_TTL_S - 1, old["id"]))
    assert S.purge_stale() == 1
    assert S.get(old["id"]) is None and S.get(fresh["id"]) is not None
    assert len(env.get(f"/jobs/{job['id']}/sources").json()) == 1


def test_deleting_an_episode_deletes_its_source_copy(env):
    job = env.post("/jobs", json={"sources": [{"id": _ready_note()["id"]}]}).json()
    main.store.update(job["id"], state="done")
    assert env.delete(f"/jobs/{job['id']}").status_code == 200
    with S.jobs_mod._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM job_sources WHERE job_id = ?", (job["id"],)).fetchone()[0] == 0
