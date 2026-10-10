import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _public_feed(monkeypatch):
    """These tests check feed content; feeds are private by default (L2)."""
    import vozonda_api.routers.feeds as feeds_mod

    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda: True)


def test_feed_contains_done_jobs_with_enclosure_and_pubdate(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    store.create("ep-a", "https://example.com/a")
    store.update("ep-a", title="Alpha", description="First & <ep>", duration_ms=91000)
    store.finish("ep-a")
    time.sleep(0.01)
    store.create("ep-b", "https://example.com/b")
    store.update("ep-b", title="Beta", description="Second ep", duration_ms=125000)
    store.finish("ep-b")
    # failed must not appear
    store.create("fail-x", "https://example.com/c")
    store.fail("fail-x", "fetch", "boom")

    client = TestClient(main_mod.app)
    res = client.get("/feed.xml")
    assert res.status_code == 200
    ctype = res.headers.get("content-type", "")
    assert "application/rss+xml" in ctype
    txt = res.text
    assert '<?xml version="1.0"' in txt
    assert "<rss" in txt
    assert "<channel>" in txt
    assert "<title>Vozonda</title>" in txt
    assert txt.count("<item>") == 2
    # newest first: ep-b before ep-a
    assert txt.index("ep-b") < txt.index("ep-a")
    # enclosure absolute url via request base url
    assert "http://testserver/audio/ep-b.mp3" in txt
    assert "http://testserver/audio/ep-a.mp3" in txt
    assert '<enclosure url="http://testserver/audio/' in txt
    assert 'type="audio/mpeg"' in txt
    # html-escaped description
    assert "First &amp; &lt;ep&gt;" in txt
    # pubDate RFC822
    assert "<pubDate>" in txt
    assert "GMT" in txt
    # itunes:duration from duration_ms
    assert "<itunes:duration>1:31</itunes:duration>" in txt
    assert "<itunes:duration>2:05</itunes:duration>" in txt
    # failed excluded
    assert "fail-x" not in txt
    # link is share page
    assert "http://testserver/e/ep-a" in txt


def test_feed_empty_when_no_done_jobs(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    jobs_mod.JobStore()

    client = TestClient(main_mod.app)
    res = client.get("/feed.xml")
    assert res.status_code == 200
    assert "application/rss+xml" in res.headers.get("content-type", "")
    assert res.text.count("<item>") == 0
    assert "<channel>" in res.text


def test_feed_v4v_splits_when_creator_address_set(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod
    import vozonda_api.settings_store as ss

    monkeypatch.delenv("VOZONDA_NODE_V4V_ADDRESS", raising=False)
    monkeypatch.delenv("VOZONDA_APP_V4V_ADDRESS", raising=False)
    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    store.create("ep-v4v", "https://example.com/v4v")
    store.update("ep-v4v", title="V4V", duration_ms=120000)
    store.finish("ep-v4v")

    # settings_store holds its own copy of DB_PATH (by-value import)
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    ss.ensure_table()
    ss.set_setting("feed.creator.address", "maker@getalby.com")
    ss.set_setting("feed.app.address", "app@vozonda.local")
    ss.set_setting("feed.creator.split", "90")

    client = TestClient(main_mod.app)
    res = client.get("/feed.xml")
    txt = res.text
    assert res.status_code == 200
    assert 'xmlns:podcast="https://podcastindex.org/namespace/1.0"' in txt
    assert '<podcast:funding url="lightning:maker@getalby.com">' in txt
    assert '<podcast:value type="lightning" method="keysend"' in txt
    assert 'address="maker@getalby.com" split="90"' in txt
    assert 'address="app@vozonda.local" split="10"' in txt
    # 120 s at 0.5 sat/s -> 60 sat suggested
    assert 'suggested="0.00000060000"' in txt


def test_feed_has_no_value_block_without_addresses(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod
    import vozonda_api.settings_store as ss

    monkeypatch.delenv("VOZONDA_NODE_V4V_ADDRESS", raising=False)
    monkeypatch.delenv("VOZONDA_APP_V4V_ADDRESS", raising=False)
    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    store.create("ep-plain", "https://example.com/p")
    store.finish("ep-plain")

    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    ss.ensure_table()

    client = TestClient(main_mod.app)
    txt = client.get("/feed.xml").text
    assert "<podcast:value" not in txt
    assert "<podcast:funding" not in txt


def test_feed_v4v_env_node_address_override(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod
    import vozonda_api.settings_store as ss

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setenv("VOZONDA_NODE_V4V_ADDRESS", "node@sparki.grid")
    ss.ensure_table()
    ss.set_setting("feed.creator.address", "maker@getalby.com")

    store = jobs_mod.JobStore()
    store.create("ep-node", "https://example.com/node")
    store.update("ep-node", title="Node Ep", duration_ms=60000)
    store.finish("ep-node")

    client = TestClient(main_mod.app)
    # Check /settings reflects locked host env address
    res_settings = client.get("/settings").json()
    assert res_settings["node_v4v_locked"] is True
    assert res_settings["settings"]["feed.app.address"] == "node@sparki.grid"

    # Check /feed.xml renders node address from env
    txt = client.get("/feed.xml").text
    assert 'address="node@sparki.grid" split="10"' in txt


def test_feed_links_use_public_url_when_set(tmp_path, monkeypatch):
    """Behind a proxy that rewrites the host (the Vite preview) the request address is 127.0.0.1; podcast
    apps on another device need the public one."""
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setenv("VOZONDA_PUBLIC_URL", "http://vozonda.example.org:4173/")
    store = jobs_mod.JobStore()
    store.create("ep-pub", "https://example.com/a")
    store.update("ep-pub", title="Alpha", duration_ms=1000)
    store.finish("ep-pub")
    txt = TestClient(main_mod.app).get("/feed.xml").text
    assert 'enclosure url="http://vozonda.example.org:4173/audio/ep-pub.mp3"' in txt
    assert "testserver" not in txt
