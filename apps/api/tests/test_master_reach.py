"""Master (default) show reach: private or podcast apps (issue #1)."""

import pathlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

import vozonda_api.jobs as jobs_mod
from vozonda_api import settings_store as ss
from vozonda_api.main import app

SETTINGS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "web" / "src" / "lib" / "components" / "SettingsScreen.svelte"
)


@pytest.fixture(autouse=True)
def _own_db(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)
    jobs_mod.init_db()
    ss.ensure_table()
    conn = sqlite3.connect(str(jobs_mod.DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
    ss.set_setting("show.name", "My Show")
    ss.set_setting("feed.public", "1")


@pytest.fixture
def client():
    return TestClient(app)


def _default(client):
    shows = client.get("/distribution").json()["shows"]
    return next(s for s in shows if s["slug"] == "default")


def test_default_is_podcast_apps_with_feed(client):
    d = _default(client)
    assert d["rss"] == "1" and d["fixed"] is True
    assert d["feed_url"].endswith("/feed.xml")
    assert client.get("/feed.xml").status_code == 200


def test_private_then_back_on(client):
    r = client.put("/shows/default/rss", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["rss"] == "0" and r.json()["feed_url"] is None
    assert client.get("/feed.xml").status_code == 404
    d = _default(client)
    assert d["rss"] == "0" and d["feed_url"] is None and d["fixed"] is True
    assert client.put("/shows/default/rss", json={"enabled": True}).json()["rss"] == "1"
    assert client.get("/feed.xml").status_code == 200
    assert _default(client)["feed_url"].endswith("/feed.xml")


def test_invalid_body_rejected(client):
    assert client.put("/shows/default/rss", json={"enabled": "yes"}).status_code == 422


def test_nostr_unchanged_and_still_undeletable(client):
    client.put("/shows/default/rss", json={"enabled": False})
    assert _default(client)["nostr"] == "0"
    assert ss.get_setting("show.default.nostr") is None
    assert client.delete("/shows/default").status_code in (400, 403, 404, 405)
    assert _default(client)["fixed"] is True


def test_numbered_show_unchanged(client):
    slug = client.post("/shows", json={"name": "Other"}).json()["slug"]
    assert client.put(f"/shows/{slug}/rss", json={"enabled": False}).json()["feed_url"] is None
    assert client.get("/feed.xml").status_code == 200


def test_settings_markup_two_option_control():
    src = SETTINGS.read_text(encoding="utf-8")
    assert "MASTER_REACHES" in src
    assert "r.id === 'private' || r.id === 'apps'" in src
    assert "disabled><Icon name=\"lock\"" not in src
    assert "Distribution of the default show" in src
