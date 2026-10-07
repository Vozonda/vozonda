"""Coordinator review of VOZONDA-NOSTR-3 (2026-10-02): deletion and retry, run for real.

The fleet tests replaced the blob loader with a plain function; the real one was an
async def iterated without await, so every deletion crashed. Blob URLs end in
'<sha256>.mp3' and the sha was read as 'everything after the last slash', so no blob
was ever found; the primary upload was never recorded; BUD-11 requires an expiration
tag on the delete token; the job delete did not trigger the Nostr deletion; retry held
the request for the whole upload; last_event_id was not per show."""
import asyncio
import base64
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from vozonda_api import nostr_orchestrator as orch

SHA = "a" * 64


@pytest.fixture
def db(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    from vozonda_api import settings_store as ss

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    jobs_mod.init_db()
    ss.ensure_table()
    orch._ensure_nostr_publish_table()
    return tmp_path


def _signed(slug, ev):
    return {**ev, "id": "d" * 64, "pubkey": "p" * 64, "sig": "s" * 128, "created_at": ev.get("created_at", int(time.time()))}


def test_deleting_an_episode_deletes_its_events_and_every_blob(db):
    orch._record_publish(job_id="job-1", kind=54, event_id_val="e" * 64, relay_url="wss://r", relay_ok=True)
    orch._record_publish(job_id="job-1", kind=5, event_id_val="f" * 64)  # an older deletion event: never targeted
    orch._record_publish(job_id="job-1", kind=0, event_id_val=None, server_url="https://a.example",
                         server_ok=True, blob_url=f"https://a.example/{SHA}.mp3")
    orch._record_publish(job_id="job-1", kind=0, event_id_val=None, server_url="https://b.example",
                         server_ok=True, blob_url=f"https://cdn.b.example/{SHA}.mp3")
    deletes, published = [], []

    def handler(req):
        deletes.append(req)
        return httpx.Response(200)

    async def fake_publish(event, relays):
        published.append(event)
        return [MagicMock(ok=True, relay="wss://r", reason=None)]

    with patch.object(orch, "sign_event", side_effect=_signed), \
         patch.object(orch, "_ensure_show_key", return_value="p" * 64), \
         patch.object(orch, "publish_async", side_effect=fake_publish), \
         patch.object(orch, "_load_relay_urls", return_value=["wss://r"]), \
         patch("vozonda_api.blossom._guard_server_url"), \
         patch("vozonda_api.blossom._client", side_effect=lambda transport=None: httpx.Client(transport=httpx.MockTransport(handler))):
        res = asyncio.run(orch.delete_published_job("job-1", show_slug="1"))
    assert [e["tags"] for e in published] == [[["e", "e" * 64], ["k", "54"]]], "only the kind 54 episode event"
    assert sorted(r.url.host for r in deletes) == ["a.example", "b.example"]
    for r in deletes:
        assert r.method == "DELETE" and r.url.path == f"/{SHA}"
        auth = json.loads(base64.b64decode(r.headers["Authorization"].split(" ", 1)[1]))
        tags = {t[0]: t[1] for t in auth["tags"]}
        assert tags["t"] == "delete" and tags["x"] == SHA
        assert int(tags["expiration"]) > time.time(), "BUD-11: an expiration tag in the future"
        assert tags["server"] == r.url.host, "a delete token only works on its own server"
    assert res["summary"] == {"events_deleted": 1, "blobs_deleted": 2}


def test_the_primary_upload_is_recorded_so_it_can_be_deleted(db):
    job = {"id": "job-2", "state": "done", "show_slug": "1", "title": "T", "og_image": ""}
    store = MagicMock()
    store.get.return_value = job
    primary = MagicMock(url=f"https://primary.example/{SHA}.mp3")
    with patch("vozonda_api.jobs.JobStore", return_value=store), \
         patch.object(orch, "_get_show_config", return_value={"nostr": "1", "name": "S", "author": "", "category": ""}), \
         patch.object(orch, "_ensure_show_key", return_value="p" * 64), \
         patch.object(orch, "_publish_show_event", return_value=None), \
         patch.object(orch, "_audio_blob_for", return_value=("/tmp/x.mp3", "audio/mpeg")), \
         patch.object(orch, "_transcript_path_for", return_value=None), \
         patch.object(orch, "_chapters_path_for", return_value=None), \
         patch.object(orch, "_load_blossom_servers", return_value=["https://primary.example"]), \
         patch.object(orch, "_upload_blob", return_value=(primary, [])), \
         patch.object(orch, "_publish_episode", return_value="ep"):
        asyncio.run(orch.publish_job("job-2"))
    blobs = orch._load_blob_descriptors_for_job("job-2")
    assert {"server_url": "https://primary.example", "sha256": SHA} in [{k: b[k] for k in ("server_url", "sha256")} for b in blobs]


def _client(db, monkeypatch):
    from fastapi.testclient import TestClient

    from vozonda_api.main import app

    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)
    return TestClient(app)


def test_retry_returns_at_once_and_publishes_in_the_background(db, monkeypatch):
    from vozonda_api.jobs import JobStore

    JobStore().create("job-3", "https://example.com/x")
    spawned = []
    monkeypatch.setattr("vozonda_api.pipeline._spawn_background", lambda coro: (spawned.append(coro), coro.close()))
    r = _client(db, monkeypatch).post("/jobs/job-3/nostr/publish")
    assert r.status_code == 200 and r.json()["queued"] is True and r.json()["retried"] is True
    assert len(spawned) == 1


def test_deleting_a_published_job_also_deletes_it_on_nostr(db, monkeypatch):
    from vozonda_api.jobs import JobStore

    store = JobStore()
    store.create("job-4", "https://example.com/y", show_slug="1")
    store.update("job-4", state="done")
    orch._record_publish(job_id="job-4", kind=54, event_id_val="e" * 64, relay_ok=True)
    calls = []

    async def fake_delete(job_id, show_slug=None):
        calls.append((job_id, show_slug))

    monkeypatch.setattr(orch, "delete_published_job", fake_delete)
    spawned = []
    monkeypatch.setattr("vozonda_api.pipeline._spawn_background", spawned.append)
    assert _client(db, monkeypatch).delete("/jobs/job-4").status_code == 200
    for coro in spawned:
        asyncio.run(coro)
    assert calls == [("job-4", "1")], "the show is captured before the job row is gone"


def test_last_event_id_is_the_shows_own(db, monkeypatch):
    client = _client(db, monkeypatch)
    one = client.post("/shows", json={"name": "One"}).json()["slug"]
    two = client.post("/shows", json={"name": "Two"}).json()["slug"]
    orch._remember_show_sha(one.lstrip("s"), "x", "event-of-one")
    orch._remember_show_sha(two.lstrip("s"), "y", "event-of-two")
    assert client.get(f"/shows/{one}/nostr").json()["last_event_id"] == "event-of-one"
    assert client.get(f"/shows/{two}/nostr").json()["last_event_id"] == "event-of-two"
