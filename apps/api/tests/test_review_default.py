"""Tests for script.review_default setting (VOZONDA-REVIEW-DEFAULT)."""

import pytest
from fastapi.testclient import TestClient

from vozonda_api import main
from vozonda_api.settings_store import get_setting, set_setting


def test_settings_defaults_contain_review_default():
    client = TestClient(main.app)
    resp = client.get("/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "script.review_default" in data["defaults"]
    assert data["defaults"]["script.review_default"] == "0"


def test_put_setting_accepts_valid_and_rejects_invalid():
    client = TestClient(main.app)

    # accepts "0"
    resp = client.put("/settings/script.review_default", json={"value": "0"})
    assert resp.status_code == 200
    assert resp.json()["value"] == "0"
    assert get_setting("script.review_default") == "0"

    # accepts "1"
    resp = client.put("/settings/script.review_default", json={"value": "1"})
    assert resp.status_code == 200
    assert resp.json()["value"] == "1"
    assert get_setting("script.review_default") == "1"

    # rejects values other than "0" or "1" with 422
    for bad in ["2", "-1", "true", "false", "yes", "no", "", "   "]:
        resp = client.put("/settings/script.review_default", json={"value": bad})
        assert resp.status_code == 422


def test_direct_set_setting_validation():
    # Direct validation in settings_store
    assert set_setting("script.review_default", "0") == "0"
    assert set_setting("script.review_default", "1") == "1"
    with pytest.raises(ValueError):
        set_setting("script.review_default", "2")
    with pytest.raises(ValueError):
        set_setting("script.review_default", "true")


def test_post_jobs_without_review_script_defaults_to_false_even_with_setting_1(monkeypatch):
    client = TestClient(main.app)

    # Set setting to "1"
    set_setting("script.review_default", "1")
    assert get_setting("script.review_default") == "1"

    # Mock pipeline start like the existing script review tests do
    started: dict = {}

    async def fake_run(job_id, runner=None):
        started[job_id] = runner

    monkeypatch.setattr(main, "_run", fake_run)

    # POST /jobs without review_script
    resp = client.post(
        "/jobs",
        json={"text": "Nostr is a simple open protocol for censorship resistant social media." * 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_script"] is False

    job = main.store.get(data["id"])
    assert job is not None
    assert job["review_script"] is False

    # Setting review_script explicitly to True still works
    resp_true = client.post(
        "/jobs",
        json={
            "text": "Nostr is a simple open protocol for censorship resistant social media." * 2,
            "review_script": True,
        },
    )
    assert resp_true.status_code == 200
    assert resp_true.json()["review_script"] is True
    job_true = main.store.get(resp_true.json()["id"])
    assert job_true is not None
    assert job_true["review_script"] is True
