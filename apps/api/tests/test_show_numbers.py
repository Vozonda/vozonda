"""Show numbers are never reused, gaps never hide shows (coordinator, 2026-10-02).

POST /shows gave a new show the lowest free number. A deleted show keeps its key file
(its Nostr identity), so a new show could publish under the old show's identity. And
every listing walked show.1, show.2, ... and stopped at the first gap, so deleting
show 1 hid all others. The default (unnumbered) show was missing from /distribution."""
import pytest
from fastapi.testclient import TestClient

from vozonda_api import settings_store as ss


@pytest.fixture
def client(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    jobs_mod.init_db()
    ss.ensure_table()
    keys = tmp_path / "keys"
    keys.mkdir()
    monkeypatch.setattr("vozonda_api.podcast_key._get_nostr_secret_dir", lambda: keys)
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)
    from vozonda_api.main import app

    return TestClient(app), keys


def test_a_deleted_shows_number_is_never_given_to_a_new_show(client):
    c, keys = client
    first = c.post("/shows", json={"name": "First"}).json()["slug"]
    (keys / f"{first.lstrip('s')}.key").write_text("secret")  # it published once
    assert c.delete(f"/shows/{first}").status_code == 200
    second = c.post("/shows", json={"name": "Second"}).json()["slug"]
    assert second != first, "a new show must never inherit the deleted show's Nostr key"


def test_a_gap_does_not_hide_the_other_shows(client, monkeypatch):
    c, _ = client
    one = c.post("/shows", json={"name": "One"}).json()["slug"]
    c.post("/shows", json={"name": "Two"})
    c.delete(f"/shows/{one}")
    assert [s["name"] for s in c.get("/shows").json()["shows"]] == ["Two"]
    names = [s["name"] for s in c.get("/distribution").json()["shows"]]
    assert "Two" in names


def test_distribution_lists_the_default_show_and_uses_the_public_address(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("VOZONDA_PUBLIC_URL", "https://pods.example.org")
    ss.set_setting("show.name", "My Default Show")
    c.post("/shows", json={"name": "Numbered"})
    shows = c.get("/distribution").json()["shows"]
    default = next(s for s in shows if s["slug"] == "default")
    assert default["name"] == "My Default Show" and default["feed_url"] == "https://pods.example.org/feed.xml"
    numbered = next(s for s in shows if s["name"] == "Numbered")
    assert numbered["feed_url"].startswith("https://pods.example.org/")
