"""Tests for Nostr publishing endpoints (VOZONDA-NOSTR-3).

Covers:
- GET /shows/{slug}/nostr - enabled, npub, last show event id
- PUT /shows/{slug}/nostr - enable/disable with 422 guard
- POST /shows/{slug}/nostr/export-nsec - export nsec with auth
- GET /jobs/{id}/nostr - publish status
- POST /jobs/{id}/nostr/publish - retry publish
- DELETE /jobs/{id}/nostr - best-effort NIP-09 + BUD-02 deletion
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import vozonda_api.jobs as jobs_mod
from vozonda_api import settings_store as ss_mod
from vozonda_api.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Isolated SQLite database for jobs and nostr_publish."""
    db_file = tmp_path / "test_jobs.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db_file)
    monkeypatch.setattr(ss_mod, "DB_PATH", db_file)

    # Loopback and billing off to keep write auth open for tests
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    jobs_mod.init_db()

    # Create all required tables
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS nostr_publish ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, "
        "kind INTEGER NOT NULL, event_id TEXT, blob_url TEXT, "
        "relay_url TEXT, server_url TEXT, relay_ok INTEGER, "
        "server_ok INTEGER, error TEXT, published_at REAL NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()

    # Stub out background pipeline execution
    async def fake_run(job_id, runner=None):
        pass

    monkeypatch.setattr("vozonda_api.main._run", fake_run)

    yield db_file


@pytest.fixture
def client(test_db):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_show_settings(num: str = "1", name: str = "My Show",
                       author: str = "Alice", nostr: str = "0") -> None:
    """Insert show settings into the test DB."""
    conn = sqlite3.connect(str(jobs_mod.DB_PATH))
    for key, value in [
        (f"show.{num}.name", name),
        (f"show.{num}.author", author),
        (f"show.{num}.nostr", nostr),
        ("nostr.publish_default", "0"),
        ("nostr.relays", "wss://relay.example.com"),
        ("nostr.blossom_servers", "https://blossom.example.com"),
    ]:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    conn.close()


def _create_job_in_db(job_id: str, state: str = "done",
                      show_slug: str = "1") -> None:
    """Insert a job record into the test DB."""
    conn = sqlite3.connect(str(jobs_mod.DB_PATH))
    conn.execute(
        "INSERT OR REPLACE INTO jobs "
        "(id, url, state, title, created_at, show_slug, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, "https://example.com/1", state, "Test Episode",
         1700000000, show_slug, 1700000000),
    )
    conn.commit()
    conn.close()


def _add_nostr_publish_row(job_id: str, kind: int, event_id: str,
                           blob_url: str = "", server_url: str = "",
                           relay_ok: int = 1) -> None:
    """Insert a row into nostr_publish table."""
    conn = sqlite3.connect(str(jobs_mod.DB_PATH))
    conn.execute(
        "INSERT INTO nostr_publish "
        "(job_id, kind, event_id, blob_url, server_url, relay_ok, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, kind, event_id, blob_url, server_url, relay_ok, 1700000000),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# GET /shows/{slug}/nostr
# ---------------------------------------------------------------------------

class TestGetShowNostr:
    def test_returns_enabled_status(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        resp = client.get("/shows/1/nostr")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True

    def test_returns_disabled_status(self, client, test_db):
        _add_show_settings(num="1", nostr="0")
        resp = client.get("/shows/1/nostr")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_returns_404_for_unknown_show(self, client, test_db):
        resp = client.get("/shows/999/nostr")
        assert resp.status_code == 404

    def test_returns_404_for_invalid_slug(self, client, test_db):
        resp = client.get("/shows/abc/nostr")
        assert resp.status_code == 404

    def test_returns_npub_when_keypair_exists(self, client, tmp_path: Path, test_db):
        _add_show_settings(num="1", nostr="1")
        with patch("vozonda_api.config.VOZONDA_SECRETS_DIR", tmp_path):
            with patch("vozonda_api.podcast_key.VOZONDA_SECRETS_DIR", tmp_path):
                from vozonda_api.podcast_key import generate_keypair
                generate_keypair("1")
                resp = client.get("/shows/1/nostr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["npub"] is not None
                assert data["npub"].startswith("npub")

    def test_returns_last_event_id_from_show_meta(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        # per show (coordinator 2026-10-02: the old query returned any show's last event)
        from vozonda_api import nostr_orchestrator as orch

        orch._ensure_nostr_publish_table()
        orch._remember_show_sha("1", "sha", "show_evt_123")
        resp = client.get("/shows/1/nostr")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_event_id"] == "show_evt_123"


# ---------------------------------------------------------------------------
# PUT /shows/{slug}/nostr
# ---------------------------------------------------------------------------

class TestPutShowNostr:
    def test_enable_without_confirm_returns_422(self, client, test_db):
        _add_show_settings(num="1", nostr="0")
        resp = client.put(
            "/shows/1/nostr",
            json={"enabled": True, "confirm_public": False},
        )
        assert resp.status_code == 422
        assert "public" in resp.json()["detail"].lower()

    def test_enable_with_confirm_succeeds(self, client, test_db):
        _add_show_settings(num="1", nostr="0")
        resp = client.put(
            "/shows/1/nostr",
            json={"enabled": True, "confirm_public": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["slug"] == "1"

    def test_disable_succeeds(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        resp = client.put(
            "/shows/1/nostr",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_404_for_unknown_show(self, client, test_db):
        resp = client.put(
            "/shows/999/nostr",
            json={"enabled": True, "confirm_public": True},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /shows/{slug}/nostr/export-nsec
# ---------------------------------------------------------------------------

class TestExportNsec:
    def test_export_returns_nsec(self, client, tmp_path: Path, test_db):
        _add_show_settings(num="1", nostr="0")
        with patch("vozonda_api.config.VOZONDA_SECRETS_DIR", tmp_path):
            with patch("vozonda_api.podcast_key.VOZONDA_SECRETS_DIR", tmp_path):
                from vozonda_api.podcast_key import generate_keypair
                generate_keypair("1")
                resp = client.post("/shows/1/nostr/export-nsec")
                assert resp.status_code == 200
                data = resp.json()
                assert data["slug"] == "1"
                assert data["nsec"].startswith("nsec")

    def test_404_when_no_keypair(self, client, test_db):
        _add_show_settings(num="1", nostr="0")
        with patch("vozonda_api.config.VOZONDA_SECRETS_DIR", Path("/tmp")):
            with patch("vozonda_api.podcast_key.VOZONDA_SECRETS_DIR", Path("/tmp")):
                resp = client.post("/shows/1/nostr/export-nsec")
                assert resp.status_code == 404

    def test_404_for_unknown_show(self, client, test_db):
        resp = client.post("/shows/999/nostr/export-nsec")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /jobs/{id}/nostr
# ---------------------------------------------------------------------------

class TestGetJobNostr:
    def test_returns_empty_events_for_new_job(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        _create_job_in_db("job-1", state="done", show_slug="1")
        resp = client.get("/jobs/job-1/nostr")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-1"
        assert data["events"] == []

    def test_returns_published_event_ids(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        _create_job_in_db("job-1", state="done", show_slug="1")
        _add_nostr_publish_row("job-1", kind=54, event_id="abc123def456",
                               relay_ok=1)
        resp = client.get("/jobs/job-1/nostr")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["kind"] == 54
        assert data["events"][0]["event_id"] == "abc123def456"

    def test_returns_404_for_unknown_job(self, client, test_db):
        resp = client.get("/jobs/unknown-job/nostr")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /jobs/{id}/nostr/publish
# ---------------------------------------------------------------------------

class TestRetryPublish:
    @pytest.mark.asyncio
    async def test_retry_calls_publish_job(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        _create_job_in_db("job-1", state="done", show_slug="1")
        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = MagicMock()
            instance.get.return_value = {
                "id": "job-1", "state": "done", "show_slug": "1",
                "title": "Test", "url": "https://example.com/1",
                "created_at": 1700000000,
            }
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator.publish_job", new_callable=AsyncMock) as mock_publish:
                resp = client.post("/jobs/job-1/nostr/publish")
                assert resp.status_code == 200
                data = resp.json()
                assert data["job_id"] == "job-1"
                assert data["retried"] is True
                mock_publish.assert_called_once_with("job-1")

    @pytest.mark.asyncio
    async def test_retry_returns_404_for_unknown_job(self, client, test_db):
        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = MagicMock()
            instance.get.side_effect = KeyError("not found")
            MockStore.return_value = instance
            resp = client.post("/jobs/nonexistent/nostr/publish")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /jobs/{id}/nostr
# ---------------------------------------------------------------------------

class TestDeleteJobNostr:
    @pytest.mark.asyncio
    async def test_delete_sends_kind5_and_blob_deletes(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        _create_job_in_db("job-1", state="done", show_slug="1")
        _add_nostr_publish_row("job-1", kind=54, event_id="evt123",
                               blob_url="https://blossom.example.com/aaaabbbbccccddddeeee"
                                        "ffff0000111122223333444455556666",
                               server_url="https://blossom.example.com", relay_ok=1)

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = MagicMock()
            instance.get.return_value = {
                "id": "job-1", "state": "done", "show_slug": "1",
                "title": "Test", "url": "https://example.com/1",
                "created_at": 1700000000,
            }
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._event_ids_for_job", return_value=[
                {"kind": 54, "event_id": "evt123"},
            ]), patch("vozonda_api.nostr_orchestrator._load_blossom_servers", return_value=[]):
                def _fake_blob_descriptors(jid):
                    return [
                        {
                            "blob_url": (
                                "https://blossom.example.com/"
                                "aaaabbbbccccddddeeeeffff"
                                "0000111122223333444455556666"
                            ),
                            "server_url": (
                                "https://blossom.example.com"
                            ),
                            "sha256": (
                                "aaaabbbbccccddddeeeeffff"
                                "0000111122223333444455556666"
                            ),
                        },
                    ]

                with patch(
                        "vozonda_api.nostr_orchestrator."
                        "_load_blob_descriptors_for_job",
                        _fake_blob_descriptors), patch(
                        "vozonda_api.nostr_orchestrator."
                        "_publish_delete_event", new_callable=AsyncMock
                ) as mock_del:
                    mock_del.return_value = "del_evt_abc"
                    with patch(
                            "vozonda_api.nostr_orchestrator."
                            "_delete_blob_on_server",
                            new_callable=AsyncMock
                    ) as mock_blob_del:
                        mock_blob_del.return_value = True
                        resp = client.delete("/jobs/job-1/nostr")
                        assert resp.status_code == 200
                        data = resp.json()
                        assert data["job_id"] == "job-1"
                        deleted = data["deleted"]
                        assert "deletions" in deleted
                        assert "blob_deletes" in deleted
                        assert len(deleted["deletions"]) == 1
                        assert deleted["deletions"][0]["event_id"] == "evt123"
                        assert deleted["deletions"][0]["status"] == "deleted"
                        assert mock_del.call_count == 1

    @pytest.mark.asyncio
    async def test_delete_records_kind5_under_job_id(self, client, test_db):
        _add_show_settings(num="1", nostr="1")
        _create_job_in_db("job-1", state="done", show_slug="1")
        _add_nostr_publish_row("job-1", kind=54, event_id="evt123",
                               relay_ok=1)

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = MagicMock()
            instance.get.return_value = {
                "id": "job-1", "state": "done", "show_slug": "1",
                "title": "Test", "url": "https://example.com/1",
                "created_at": 1700000000,
            }
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._event_ids_for_job", return_value=[
                {"kind": 54, "event_id": "evt123"},
            ]), patch("vozonda_api.nostr_orchestrator._load_blossom_servers", return_value=[]):
                def _fake_blob_descriptors(jid):
                    return []

                with patch(
                        "vozonda_api.nostr_orchestrator."
                        "_load_blob_descriptors_for_job",
                        _fake_blob_descriptors), patch(
                        "vozonda_api.nostr_orchestrator."
                        "_publish_delete_event", new_callable=AsyncMock
                ) as mock_del:
                    mock_del.return_value = "del_evt_abc"
                    resp = client.delete("/jobs/job-1/nostr")
                    assert resp.status_code == 200
                    # Verify _publish_delete_event was called with job_id
                    mock_del.assert_called_once()
                    call_args = mock_del.call_args
                    # Signature: _publish_delete_event(show_slug, job_id, target_event_id, kind)
                    assert call_args[0] == ("1", "job-1", "evt123", 54)

    @pytest.mark.asyncio
    async def test_delete_returns_404_for_unknown_job(self, client, test_db):
        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = MagicMock()
            instance.get.side_effect = KeyError("not found")
            MockStore.return_value = instance
            resp = client.delete("/jobs/nonexistent/nostr")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth gate: mutating endpoints require write auth
# ---------------------------------------------------------------------------

class TestAuthGate:
    def test_put_requires_auth(self, client, test_db):
        _add_show_settings(num="1")
        with patch.dict("os.environ", {"VOZONDA_TOKEN": "test-token"}):
            resp = client.put(
                "/shows/1/nostr",
                json={"enabled": True, "confirm_public": True},
            )
            assert resp.status_code == 401

    def test_post_export_requires_auth(self, client, tmp_path: Path, test_db):
        _add_show_settings(num="1")
        with patch.dict("os.environ", {"VOZONDA_TOKEN": "test-token"}):
            with patch("vozonda_api.config.VOZONDA_SECRETS_DIR", tmp_path):
                with patch("vozonda_api.podcast_key.VOZONDA_SECRETS_DIR", tmp_path):
                    from vozonda_api.podcast_key import generate_keypair
                    generate_keypair("1")
                    resp = client.post("/shows/1/nostr/export-nsec")
                    assert resp.status_code == 401

    def test_publish_retry_requires_auth(self, client, test_db):
        with patch.dict("os.environ", {"VOZONDA_TOKEN": "test-token"}):
            resp = client.post("/jobs/job-1/nostr/publish")
            assert resp.status_code == 401

    def test_delete_requires_auth(self, client, test_db):
        with patch.dict("os.environ", {"VOZONDA_TOKEN": "test-token"}):
            resp = client.delete("/jobs/job-1/nostr")
            assert resp.status_code == 401