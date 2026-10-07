"""Tests for agent webhooks and Idempotency-Key (VOZONDA-AGENT-2).

Covers:
- Done job delivers once with the right body
- Signature matches HMAC of the body when VOZONDA_WEBHOOK_SECRET is set
- Callback to http://127.0.0.1 is refused by SSRF guard
- 3 failed attempts stop without raising
- Idempotency-Key returns the same job id twice and creates one job
- Additional edge cases (expiry, length validation, schemes, failed jobs)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from vozonda_api import webhooks
from vozonda_api.fetcher import FetchError, guarded_client
from vozonda_api.jobs import JobStore, init_db
from vozonda_api.main import app


@pytest.mark.asyncio
async def test_done_job_delivers_once_with_right_body(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"received": True})

    def fake_guarded_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)
    monkeypatch.delenv("VOZONDA_WEBHOOK_SECRET", raising=False)

    job = {
        "id": "job-done-42",
        "state": "done",
        "title": "My Great Podcast",
        "callback_url": "https://agent.example.com/webhook",
        "duration_ms": 123456,
        "error": None,
    }
    result = await webhooks.deliver(job)
    assert result is True
    assert len(captured) == 1

    req = captured[0]
    assert str(req.url) == "https://agent.example.com/webhook"
    assert req.method == "POST"
    assert req.headers["content-type"] == "application/json"

    data = json.loads(req.content.decode("utf-8"))
    assert set(data.keys()) == {"id", "state", "title", "audio_url", "feed_url", "duration_ms", "error"}
    assert data["id"] == "job-done-42"
    assert data["state"] == "done"
    assert data["title"] == "My Great Podcast"
    assert data["audio_url"] == "/audio/job-done-42.mp3"
    assert data["duration_ms"] == 123456
    assert data["error"] is None


@pytest.mark.asyncio
async def test_failed_job_delivers_with_error(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    def fake_guarded_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)
    monkeypatch.delenv("VOZONDA_WEBHOOK_SECRET", raising=False)

    job = {
        "id": "job-fail-99",
        "state": "failed",
        "title": "Failed Episode",
        "callback_url": "https://agent.example.com/fail-hook",
        "duration_ms": 2500,
        "error": "article fetch failed",
    }
    result = await webhooks.deliver(job)
    assert result is True
    assert len(captured) == 1

    data = json.loads(captured[0].content.decode("utf-8"))
    assert data["id"] == "job-fail-99"
    assert data["state"] == "failed"
    assert data["audio_url"] is None
    assert data["error"] == "article fetch failed"


@pytest.mark.asyncio
async def test_signature_matches_hmac_when_secret_set(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    def fake_guarded_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    secret = "test-webhook-secret-999"
    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)
    monkeypatch.setenv("VOZONDA_WEBHOOK_SECRET", secret)

    job = {
        "id": "job-sig-1",
        "state": "done",
        "title": "HMAC Verification",
        "callback_url": "https://agent.example.com/signed-webhook",
        "duration_ms": 10000,
        "error": None,
    }
    result = await webhooks.deliver(job)
    assert result is True
    assert len(captured) == 1

    req = captured[0]
    sig_header = req.headers.get("x-vozonda-signature")
    vozonda_sig = req.headers.get("x-vozonda-signature")
    assert sig_header is not None
    assert sig_header.startswith("sha256=")
    assert vozonda_sig is not None
    assert vozonda_sig.startswith("sha256=")

    expected_mac = hmac.new(secret.encode("utf-8"), req.content, hashlib.sha256).hexdigest()
    assert sig_header == f"sha256={expected_mac}"
    assert vozonda_sig == f"sha256={expected_mac}"


@pytest.mark.asyncio
async def test_callback_to_loopback_refused_by_guard(monkeypatch):
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"ok": True})

    def fake_guarded_client(**kwargs):
        from vozonda_api.fetcher import _guard_request

        hooks = dict(kwargs.pop("event_hooks", None) or {})
        hooks["request"] = [_guard_request, *hooks.get("request", [])]
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), event_hooks=hooks, **kwargs)

    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)

    job = {
        "id": "job-ssrf-1",
        "state": "done",
        "title": "Local Attack",
        "callback_url": "http://127.0.0.1:8787/hook",
    }
    result = await webhooks.deliver(job)
    assert result is False
    assert called is False


@pytest.mark.asyncio
async def test_guarded_client_directly_refuses_loopback():
    async with guarded_client(transport=httpx.MockTransport(lambda req: httpx.Response(200))) as client:
        with pytest.raises(FetchError, match="local"):
            await client.post("http://127.0.0.1:8787/test")



@pytest.mark.asyncio
async def test_three_failed_attempts_stop_without_raising(monkeypatch):
    attempts = 0
    slept_delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, text="Internal Server Error")

    def fake_guarded_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    async def fake_sleep(seconds: float):
        slept_delays.append(seconds)

    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    job = {
        "id": "job-retry-1",
        "state": "failed",
        "title": "Failing Hook",
        "callback_url": "https://example.com/failing-endpoint",
        "duration_ms": 1000,
        "error": "extract failed",
    }
    result = await webhooks.deliver(job)
    assert result is False
    assert attempts == 3
    assert slept_delays == [1.0, 4.0]


def test_idempotency_key_returns_same_job_id_twice(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    test_db = tmp_path / "test_idempotency.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", test_db)
    init_db()

    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)

    async def fake_run(job_id, runner=None):
        pass

    monkeypatch.setattr("vozonda_api.main._run", fake_run)

    client = TestClient(app)

    key = "agent-unique-key-12345"
    payload1 = {
        "text": "This is the first version of the article text that exceeds twenty characters."
    }
    payload2 = {
        "text": "This is a completely different second article text that also exceeds twenty characters."
    }

    res1 = client.post("/jobs", json=payload1, headers={"Idempotency-Key": key})
    assert res1.status_code == 200, res1.text
    data1 = res1.json()
    job_id_1 = data1["id"]

    res2 = client.post("/jobs", json=payload2, headers={"Idempotency-Key": key})
    assert res2.status_code == 200, res2.text
    data2 = res2.json()
    job_id_2 = data2["id"]

    assert job_id_1 == job_id_2

    with sqlite3.connect(test_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 1


def test_idempotency_key_expires_after_24_hours(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    test_db = tmp_path / "test_expiry.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", test_db)
    init_db()
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)

    async def fake_run(job_id, runner=None):
        pass

    monkeypatch.setattr("vozonda_api.main._run", fake_run)
    client = TestClient(app)

    key = "expiring-key-xyz"
    res1 = client.post(
        "/jobs",
        json={"text": "First article text that is sufficiently long for vozonda."},
        headers={"Idempotency-Key": key},
    )
    assert res1.status_code == 200
    job1_id = res1.json()["id"]

    # Age the key past 24 hours (90000 seconds ago)
    with sqlite3.connect(test_db) as conn:
        conn.execute("UPDATE idempotency_keys SET created_at = created_at - 90000 WHERE key = ?", (key,))

    res2 = client.post(
        "/jobs",
        json={"text": "Second article text that is sufficiently long for vozonda."},
        headers={"Idempotency-Key": key},
    )
    assert res2.status_code == 200
    job2_id = res2.json()["id"]

    assert job1_id != job2_id
    with sqlite3.connect(test_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 2


def test_idempotency_key_max_length(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    test_db = tmp_path / "test_len.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", test_db)
    init_db()
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)

    client = TestClient(app)

    long_key = "k" * 201
    res = client.post(
        "/jobs",
        json={"text": "Valid text that is longer than twenty characters."},
        headers={"Idempotency-Key": long_key},
    )
    assert res.status_code == 422


def test_callback_url_validation(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    test_db = tmp_path / "test_cb_val.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", test_db)
    init_db()
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)

    client = TestClient(app)

    # Invalid scheme
    res = client.post(
        "/jobs",
        json={
            "text": "Valid text that is longer than twenty characters.",
            "callback_url": "ftp://bad.example.com/hook",
        },
    )
    assert res.status_code == 422

    # Too long (> 2048 chars)
    res2 = client.post(
        "/jobs",
        json={
            "text": "Valid text that is longer than twenty characters.",
            "callback_url": "https://example.com/" + "a" * 2040,
        },
    )
    assert res2.status_code == 422


@pytest.mark.asyncio
async def test_job_finish_schedules_webhook_delivery_once(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    test_db = tmp_path / "test_pipeline_webhook.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", test_db)
    init_db()

    delivered_jobs: list[dict] = []

    async def fake_deliver(job: dict) -> bool:
        delivered_jobs.append(job)
        return True

    monkeypatch.setattr("vozonda_api.webhooks.deliver", fake_deliver)

    job_store = JobStore()
    job = job_store.create(
        "job-auto-1",
        "https://example.com/article",
        callback_url="https://agent.example.com/webhook",
    )
    assert job["callback_url"] == "https://agent.example.com/webhook"

    done_job = job_store.finish("job-auto-1")
    assert done_job["state"] == "done"
    assert done_job["audio_url"] == "/audio/job-auto-1.mp3"

    await asyncio.sleep(0.01)

    assert len(delivered_jobs) == 1
    assert delivered_jobs[0]["id"] == "job-auto-1"
    assert delivered_jobs[0]["state"] == "done"
    assert delivered_jobs[0]["audio_url"] == "/audio/job-auto-1.mp3"

    # Repeated finish call must not deliver again
    job_store.finish("job-auto-1")
    await asyncio.sleep(0.01)
    assert len(delivered_jobs) == 1


@pytest.mark.asyncio
async def test_job_fail_schedules_webhook_delivery_once(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    test_db = tmp_path / "test_pipeline_fail_webhook.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", test_db)
    init_db()

    delivered_jobs: list[dict] = []

    async def fake_deliver(job: dict) -> bool:
        delivered_jobs.append(job)
        return True

    monkeypatch.setattr("vozonda_api.webhooks.deliver", fake_deliver)

    job_store = JobStore()
    job = job_store.create(
        "job-auto-fail",
        "https://example.com/article",
        callback_url="https://agent.example.com/webhook",
    )
    assert job["callback_url"] == "https://agent.example.com/webhook"

    failed_job = job_store.fail("job-auto-fail", "extract", "unreachable source")
    assert failed_job["state"] == "failed"
    assert failed_job["audio_url"] is None
    assert failed_job["error"] == "unreachable source"

    await asyncio.sleep(0.01)

    assert len(delivered_jobs) == 1
    assert delivered_jobs[0]["id"] == "job-auto-fail"
    assert delivered_jobs[0]["state"] == "failed"
    assert delivered_jobs[0]["error"] == "unreachable source"
    assert delivered_jobs[0]["audio_url"] is None

    # Repeated fail call must not deliver again
    job_store.fail("job-auto-fail", "extract", "unreachable source")
    await asyncio.sleep(0.01)
    assert len(delivered_jobs) == 1


@pytest.mark.asyncio
async def test_webhook_audio_url_absolute_when_public_base_stored(monkeypatch):
    """When public_base is stored with the job, audio_url and feed_url are absolute."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"received": True})

    def fake_guarded_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)
    monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)

    job = {
        "id": "job-abs-1",
        "state": "done",
        "title": "Absolute URL Test",
        "callback_url": "https://agent.example.com/webhook",
        "duration_ms": 10000,
        "error": None,
        "public_base": "https://vozonda.example.com",
    }
    result = await webhooks.deliver(job)
    assert result is True
    assert len(captured) == 1

    data = json.loads(captured[0].content.decode("utf-8"))
    assert data["audio_url"] == "https://vozonda.example.com/audio/job-abs-1.mp3"
    assert data["feed_url"] == "https://vozonda.example.com/feed.xml"


@pytest.mark.asyncio
async def test_webhook_audio_url_env_override_wins(monkeypatch):
    """VOZONDA_PUBLIC_URL env var overrides the stored public_base."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"received": True})

    def fake_guarded_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)
    monkeypatch.setenv("VOZONDA_PUBLIC_URL", "https://override.example.com")

    job = {
        "id": "job-env-1",
        "state": "done",
        "title": "Env Override Test",
        "callback_url": "https://agent.example.com/webhook",
        "duration_ms": 10000,
        "error": None,
        "public_base": "https://stored.example.com",
    }
    result = await webhooks.deliver(job)
    assert result is True
    assert len(captured) == 1

    data = json.loads(captured[0].content.decode("utf-8"))
    assert data["audio_url"] == "https://override.example.com/audio/job-env-1.mp3"
    assert data["feed_url"] == "https://override.example.com/feed.xml"

    monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)


@pytest.mark.asyncio
async def test_webhook_audio_url_relative_when_no_base(monkeypatch):
    """Without public_base or VOZONDA_PUBLIC_URL, audio_url stays relative."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"received": True})

    def fake_guarded_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(webhooks, "guarded_client", fake_guarded_client)
    monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)

    job = {
        "id": "job-rel-1",
        "state": "done",
        "title": "Relative URL Test",
        "callback_url": "https://agent.example.com/webhook",
        "duration_ms": 10000,
        "error": None,
        "public_base": None,
    }
    result = await webhooks.deliver(job)
    assert result is True
    assert len(captured) == 1

    data = json.loads(captured[0].content.decode("utf-8"))
    assert data["audio_url"] == "/audio/job-rel-1.mp3"
    assert data["feed_url"] is None
