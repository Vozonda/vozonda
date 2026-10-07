"""A job is linked to its numbered show, so the show's Nostr opt-in can be found.

Shows live in settings as show.<n>.* (exposed as slug 's<n>'); a job only carries the
show NAME. NOSTR-1 stored a slug derived from the name ('My Show' -> 'my-show'), which
never matches show.<n>.nostr, so an opted-in show would never publish (2026-10-02)."""
import pytest
from fastapi.testclient import TestClient

from vozonda_api.jobs import init_db
from vozonda_api.main import _show_index_for, app


@pytest.fixture
def client(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    init_db()
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)

    async def fake_run(job_id, runner=None):
        pass

    monkeypatch.setattr("vozonda_api.main._run", fake_run)
    return TestClient(app)


def _job(client, show_name):
    body = {"text": "An article text that is clearly longer than twenty characters for the job.", "show_name": show_name}
    res = client.post("/jobs", json=body)
    assert res.status_code == 200, res.text
    return client.get(f"/jobs/{res.json()['id']}").json()


def test_job_links_to_the_numbered_show_by_its_exact_name(client):
    assert client.post("/shows", json={"name": "Morning Brief"}).status_code == 200
    assert client.post("/shows", json={"name": "My Show"}).status_code == 200
    job = _job(client, "My Show")
    assert job["show_slug"] == "2", "must match the settings key show.2.nostr"
    assert _show_index_for("  my show ") == "2"


def test_unknown_or_missing_show_name_links_to_nothing(client):
    client.post("/shows", json={"name": "My Show"})
    assert _job(client, "Other Show")["show_slug"] == ""
    assert _show_index_for(None) is None and _show_index_for("") is None
