"""Tests for renaming jobs via PATCH /jobs/{job_id}."""

import uuid

import pytest
from fastapi.testclient import TestClient

from vozonda_api.main import app, store
from vozonda_api.settings_store import get_private_feed_key


@pytest.fixture
def client():
    return TestClient(app)


def test_rename_done_job(client):
    job_id = f"done-{uuid.uuid4().hex[:6]}"
    store.create(job_id, "https://example.com/episode")
    store.update(job_id, state="done", title="Original Title")

    resp = client.patch(f"/jobs/{job_id}", json={"title": "Renamed Episode Title"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == job_id
    assert data["title"] == "Renamed Episode Title"
    assert data["state"] == "done"

    job = store.get(job_id)
    assert job["title"] == "Renamed Episode Title"
    stages = {s["name"]: s for s in job["stages"]}
    assert stages["script"]["meta"]["title_edited"] is True


def test_rename_whitespace_collapsed(client):
    job_id = f"ws-{uuid.uuid4().hex[:6]}"
    store.create(job_id, "https://example.com/ws")

    resp = client.patch(
        f"/jobs/{job_id}",
        json={"title": "  Multiple   spaces    in   title  "},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Multiple spaces in title"
    assert store.get(job_id)["title"] == "Multiple spaces in title"


def test_rename_validation_empty_and_too_long(client):
    job_id = f"val-{uuid.uuid4().hex[:6]}"
    store.create(job_id, "https://example.com/val")
    store.update(job_id, title="Unchanged Title")

    # Empty string
    resp = client.patch(f"/jobs/{job_id}", json={"title": ""})
    assert resp.status_code == 422

    # Whitespace only
    resp = client.patch(f"/jobs/{job_id}", json={"title": "   \n\t  "})
    assert resp.status_code == 422

    # Exceeds 120 chars (121 chars)
    resp = client.patch(f"/jobs/{job_id}", json={"title": "a" * 121})
    assert resp.status_code == 422

    # Exactly 120 chars succeeds
    resp = client.patch(f"/jobs/{job_id}", json={"title": "a" * 120})
    assert resp.status_code == 200
    assert resp.json()["title"] == "a" * 120
    assert store.get(job_id)["title"] == "a" * 120


def test_rename_unknown_id(client):
    resp = client.patch("/jobs/unknown-job-id-99999", json={"title": "New Title"})
    assert resp.status_code == 404
    assert "job not found" in resp.json()["detail"]


def test_rename_auth_required_when_token_set(client, monkeypatch):
    job_id = f"auth-{uuid.uuid4().hex[:6]}"
    store.create(job_id, "https://example.com/auth")
    monkeypatch.setenv("VOZONDA_TOKEN", "secret-token-123")

    # Missing authorization header
    resp = client.patch(f"/jobs/{job_id}", json={"title": "New Title"})
    assert resp.status_code == 401

    # Invalid authorization token
    resp = client.patch(
        f"/jobs/{job_id}",
        json={"title": "New Title"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401

    # Valid authorization token
    resp = client.patch(
        f"/jobs/{job_id}",
        json={"title": "Authorized Title"},
        headers={"Authorization": "Bearer secret-token-123"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Authorized Title"


def test_feed_item_shows_new_title(client):
    job_id = f"feed-{uuid.uuid4().hex[:6]}"
    store.create(job_id, "https://example.com/feed")
    store.update(job_id, state="done", title="Initial Feed Title")

    key = get_private_feed_key()
    resp_initial = client.get(f"/feed.xml?key={key}")
    assert resp_initial.status_code == 200
    assert "<title>Initial Feed Title</title>" in resp_initial.text

    # Rename episode
    resp_rename = client.patch(f"/jobs/{job_id}", json={"title": "Updated Feed Title"})
    assert resp_rename.status_code == 200

    resp_updated = client.get(f"/feed.xml?key={key}")
    assert resp_updated.status_code == 200
    assert "<title>Updated Feed Title</title>" in resp_updated.text
    assert "<title>Initial Feed Title</title>" not in resp_updated.text


def test_rename_works_for_any_state(client):
    job_id = f"queued-{uuid.uuid4().hex[:6]}"
    store.create(job_id, "https://example.com/queued")

    resp = client.patch(f"/jobs/{job_id}", json={"title": "Queued Episode Title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Queued Episode Title"
    assert store.get(job_id)["title"] == "Queued Episode Title"
