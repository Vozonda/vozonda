"""Watchlist publishes into a show (VOZONDA-WATCHLIST-SHOW).

A watchlist can name a numbered show (settings show.<n>.*). Every job the
poller creates then carries that show's fields, so publish_job and the
master-feed filter treat it like a manual episode of the show. A
per-watchlist feed whose show has RSS off answers 404. Empty keeps today's
behaviour exactly.
"""

import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

import vozonda_api.jobs as jobs_mod
from vozonda_api import settings_store as ss
from vozonda_api.main import app
from vozonda_api.watchlist import (
    create_watchlist,
    get_watchlist,
    init_watchlist_db,
)


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Show Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Story One</title>
      <link>https://example.com/story-one</link>
      <guid>https://example.com/story-one</guid>
    </item>
    <item>
      <title>Story Two</title>
      <link>https://example.com/story-two</link>
      <guid>https://example.com/story-two</guid>
    </item>
    <item>
      <title>Story Three</title>
      <link>https://example.com/story-three</link>
      <guid>https://example.com/story-three</guid>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_jobs.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db_file)
    monkeypatch.setattr(ss, "DB_PATH", db_file)
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)

    jobs_mod.init_db()
    ss.ensure_table()
    init_watchlist_db()

    async def fake_run(job_id, runner=None):
        pass

    monkeypatch.setattr("vozonda_api.main._run", fake_run)
    monkeypatch.setattr("vozonda_api.watchlist_poller._run", fake_run, raising=False)
    yield db_file


@pytest.fixture
def client(test_db):
    return TestClient(app)


def _make_show(client, name="Morning Show"):
    return client.post("/shows", json={"name": name}).json()["slug"]


def _num(slug):
    return slug.lstrip("s")


def test_migration_keeps_old_rows(test_db):
    conn = sqlite3.connect(str(test_db))
    conn.execute("DROP TABLE watchlist")
    conn.execute(
        "CREATE TABLE watchlist (id TEXT PRIMARY KEY, feed_url TEXT NOT NULL UNIQUE,"
        " style TEXT NOT NULL DEFAULT 'balanced', format TEXT NOT NULL DEFAULT 'dialog',"
        " language TEXT NOT NULL DEFAULT 'auto', hosts INTEGER NOT NULL DEFAULT 2,"
        " created_at REAL NOT NULL, last_checked REAL, enabled INTEGER NOT NULL DEFAULT 1)"
    )
    conn.execute(
        "INSERT INTO watchlist (id, feed_url, created_at, enabled) VALUES (?, ?, ?, ?)",
        ("oldfeed1", "https://example.com/old.xml", 1700000000, 1),
    )
    conn.commit()
    conn.close()
    init_watchlist_db()
    wl = get_watchlist("oldfeed1")
    assert wl["feed_url"] == "https://example.com/old.xml"
    assert wl["show_slug"] == ""


def test_unknown_show_422(client):
    r = client.post("/watchlist", json={"feed_url": "https://example.com/unknown-show.xml", "show_slug": "999"})
    assert r.status_code == 422
    wl = create_watchlist("https://example.com/known.xml")
    r = client.put(f"/watchlist/{wl['id']}", json={"show_slug": "999"})
    assert r.status_code == 422


def test_create_update_get_show_slug(client):
    slug = _make_show(client)
    num = _num(slug)
    r = client.post("/watchlist", json={"feed_url": "https://example.com/with-show.xml", "show_slug": num})
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    assert r.json()["show_slug"] == num
    assert client.get(f"/watchlist/{wid}").json()["show_slug"] == num
    assert any(w["id"] == wid and w["show_slug"] == num for w in client.get("/watchlist").json()["watchlist"])
    # s-prefixed slug normalizes to the number
    r = client.put(f"/watchlist/{wid}", json={"show_slug": slug})
    assert r.status_code == 200
    assert r.json()["show_slug"] == num
    # clearing keeps today's behaviour
    r = client.put(f"/watchlist/{wid}", json={"show_slug": ""})
    assert r.status_code == 200
    assert r.json()["show_slug"] == ""


def test_no_show_unchanged(client):
    wl = create_watchlist("https://example.com/no-show.xml")
    assert wl["show_slug"] == ""
    assert client.get(f"/watchlist/{wl['id']}").json()["show_slug"] == ""


def test_poller_jobs_carry_show_fields(client, test_db, monkeypatch):
    import vozonda_api.watchlist_poller as poller

    slug = _make_show(client, "Carry Show")
    num = _num(slug)
    wl = create_watchlist("https://example.com/carry.xml", show_slug=num)

    async def fake_fetch(url):
        if "digest" in url:
            return SAMPLE_RSS.replace("story-", "digest-story-")
        return SAMPLE_RSS

    monkeypatch.setattr(poller, "fetch_feed_text", fake_fetch)

    store = jobs_mod.JobStore()
    tasks: dict = {}
    listeners: dict = {}
    created = asyncio.run(poller.poll_single(get_watchlist(wl["id"]), store, tasks, listeners, is_manual=True))
    assert len(created) >= 1
    for job_id in created:
        job = store.get(job_id)
        assert job["show_slug"] == num
        assert job["show_name"] == "Carry Show"

    # digest path carries the show too
    for t in list(tasks.values()):
        t.cancel()
    wl2 = create_watchlist("https://example.com/carry-digest.xml", show_slug=num)
    res = asyncio.run(
        poller.trigger_watchlist_digest(wl2["id"], store, {}, {}, count=2, min_entries=1, is_scheduled=False)
    )
    assert res is not None
    djob = store.get(res["digest_job"])
    assert djob["show_slug"] == num
    assert djob["show_name"] == "Carry Show"


def test_poller_no_show_carries_nothing(test_db, monkeypatch):
    import vozonda_api.watchlist_poller as poller

    wl = create_watchlist("https://example.com/plain.xml")

    async def fake_fetch(url):
        return SAMPLE_RSS

    monkeypatch.setattr(poller, "fetch_feed_text", fake_fetch)

    store = jobs_mod.JobStore()
    created = asyncio.run(poller.poll_single(get_watchlist(wl["id"]), store, {}, {}, is_manual=True))
    assert len(created) >= 1
    for job_id in created:
        job = store.get(job_id)
        assert (job.get("show_slug") or "") == ""


def test_watchlist_feed_404_for_rss_off_show(client, test_db, monkeypatch):
    import vozonda_api.routers.feeds as feeds_mod

    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda: True)
    slug = _make_show(client, "Quiet Show")
    num = _num(slug)
    ss.set_setting(f"show.{num}.rss", "0")
    r = client.post("/watchlist", json={"feed_url": "https://example.com/rss-off.xml", "show_slug": num})
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    conn = sqlite3.connect(str(test_db))
    conn.execute(
        "INSERT OR REPLACE INTO jobs (id, url, state, title, created_at, updated_at, watchlist_id, show_slug, show_name) VALUES (?, ?, 'done', ?, ?, ?, ?, ?, ?)",
        ("ep-rss-off", "https://example.com/ep1", "Gone Episode", 1700000000, 1700000000, wid, num, "Quiet Show"),
    )
    conn.commit()
    conn.close()
    r = client.get(f"/vozonda/{wid}/feed.xml")
    assert r.status_code == 404
    # rss on again: the feed answers
    ss.set_setting(f"show.{num}.rss", "1")
    r = client.get(f"/vozonda/{wid}/feed.xml")
    assert r.status_code == 200


def test_default_show_watchlist(client, test_db, monkeypatch):
    import vozonda_api.routers.feeds as feeds_mod
    import vozonda_api.watchlist_poller as poller

    # 1. Without show.name configured, 'default' is rejected with 422
    ss.set_setting("show.name", "")
    r = client.post("/watchlist", json={"feed_url": "https://example.com/def-none.xml", "show_slug": "default"})
    assert r.status_code == 422
    assert "default show not configured" in r.text

    # 2. Configure default show
    ss.set_setting("show.name", "Main Sovgrid Podcast")
    ss.set_setting("show.author", "Sovgrid Team")
    ss.set_setting("show.category", "Technology")

    # 3. Create watchlist referencing 'default' show
    r = client.post("/watchlist", json={"feed_url": "https://example.com/def-ok.xml", "show_slug": "default"})
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    assert r.json()["show_slug"] == "default"

    # 4. GET /watchlist/{id} reports show_slug="default"
    assert client.get(f"/watchlist/{wid}").json()["show_slug"] == "default"

    # 5. Poller carries default show metadata
    async def fake_fetch(url):
        return SAMPLE_RSS

    monkeypatch.setattr(poller, "fetch_feed_text", fake_fetch)
    store = jobs_mod.JobStore()
    tasks: dict = {}
    listeners: dict = {}
    created = asyncio.run(poller.poll_single(get_watchlist(wid), store, tasks, listeners, is_manual=True))
    assert len(created) >= 1
    for job_id in created:
        job = store.get(job_id)
        assert job["show_slug"] == "default"
        assert job["show_name"] == "Main Sovgrid Podcast"

    # 6. Feed respect RSS setting for default show
    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda: True)
    ss.set_setting("show.default.rss", "0")
    conn = sqlite3.connect(str(test_db))
    conn.execute(
        "INSERT OR REPLACE INTO jobs (id, url, state, title, created_at, updated_at, watchlist_id, show_slug, show_name) VALUES (?, ?, 'done', ?, ?, ?, ?, ?, ?)",
        ("ep-def-off", "https://example.com/ep-def", "Def Ep", 1700000000, 1700000000, wid, "default", "Main Sovgrid Podcast"),
    )
    conn.commit()
    conn.close()
    r = client.get(f"/vozonda/{wid}/feed.xml")
    assert r.status_code == 404

    ss.set_setting("show.default.rss", "1")
    r = client.get(f"/vozonda/{wid}/feed.xml")
    assert r.status_code == 200

    # 7. Reset to none works
    r = client.put(f"/watchlist/{wid}", json={"show_slug": ""})
    assert r.status_code == 200
    assert r.json()["show_slug"] == ""

