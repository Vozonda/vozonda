def test_watchlist_crud(jobs_db, api_client):
    client = api_client

    # create
    resp = client.post("/watchlist", json={"feed_url": "https://example.com/rss.xml", "style": "balanced", "format": "dialog", "language": "auto", "hosts": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["feed_url"] == "https://example.com/rss.xml"
    assert data["style"] == "balanced"
    wid = data["id"]

    # list
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert len(resp.json()["watchlist"]) == 1

    # duplicate -> 409
    resp = client.post("/watchlist", json={"feed_url": "https://example.com/rss.xml"})
    assert resp.status_code == 409

    # delete
    resp = client.delete(f"/watchlist/{wid}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == wid

    # list empty
    resp = client.get("/watchlist")
    assert resp.json()["watchlist"] == []

    # delete missing -> 404
    resp = client.delete(f"/watchlist/{wid}")
    assert resp.status_code == 404


def test_watchlist_validation(jobs_db, api_client):
    client = api_client

    # invalid style
    resp = client.post("/watchlist", json={"feed_url": "https://example.com/a.xml", "style": "unknown"})
    assert resp.status_code == 422

    # invalid format
    resp = client.post("/watchlist", json={"feed_url": "https://example.com/b.xml", "format": "bad"})
    assert resp.status_code == 422

    # invalid hosts
    resp = client.post("/watchlist", json={"feed_url": "https://example.com/c.xml", "hosts": 9})
    assert resp.status_code == 422

    # ssrf guard blocks loopback
    resp = client.post("/watchlist", json={"feed_url": "http://127.0.0.1/rss.xml"})
    assert resp.status_code == 422
    assert "local address" in resp.text.lower()

    # missing feed_url -> 422 from pydantic
    resp = client.post("/watchlist", json={})
    assert resp.status_code == 422


def test_watchlist_jobs_provenance(jobs_db, api_client):
    import vozonda_api.jobs as jobs_mod

    store = jobs_mod.JobStore()
    client = api_client

    # create watchlist
    resp = client.post("/watchlist", json={"feed_url": "https://example.com/feed.xml"})
    wid = resp.json()["id"]

    # simulate poller creating a job with watchlist_id
    # use store directly
    from vozonda_api.main import _readable_id

    jid = _readable_id("https://example.com/article-1")
    store.create(jid, "https://example.com/article-1", "balanced", "dialog", "neutral", "auto", watchlist_id=wid)
    store.update(jid, title="Auto Ep", description="from watchlist")
    store.finish(jid)

    # GET /jobs should expose watchlist_id
    resp = client.get("/jobs?limit=10")
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    auto = [j for j in jobs if j["url"] == "https://example.com/article-1"]
    assert len(auto) == 1
    assert auto[0]["watchlist_id"] == wid

    # GET /jobs/{id} should also
    resp = client.get(f"/jobs/{jid}")
    assert resp.json()["watchlist_id"] == wid


def test_parse_feed_types():
    from vozonda_api.watchlist_poller import parse_feed

    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item><title>E1</title><link>https://example.com/a1</link><guid>https://example.com/a1</guid></item><item><title>E2</title><link>https://example.com/a2</link></item></channel></rss>"""
    entries = parse_feed(rss)
    assert len(entries) == 2
    assert entries[0]["link"] == "https://example.com/a1"
    assert entries[1]["link"] == "https://example.com/a2"

    atom = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>T</title><entry><title>E1</title><id>https://example.com/b1</id><link href="https://example.com/b1" rel="alternate"/></entry></feed>"""
    entries = parse_feed(atom)
    assert len(entries) == 1
    assert entries[0]["link"] == "https://example.com/b1"

    # podcast RSS with enclosure url fallback (missing item link)
    podcast_rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>Podcast</title><item><title>Episode 1</title><guid>urn:uuid:12345</guid><enclosure url="https://example.com/ep1.mp3" length="1234" type="audio/mpeg"/></item></channel></rss>"""
    entries = parse_feed(podcast_rss)
    assert len(entries) == 1
    assert entries[0]["guid"] == "urn:uuid:12345"
    assert entries[0]["link"] == "https://example.com/ep1.mp3"
    assert entries[0]["title"] == "Episode 1"

    # RDF / RSS 1.0
    rdf = """<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"><channel rdf:about="https://example.com/"><title>RDF</title><link>https://example.com/</link></channel><item rdf:about="https://example.com/item1"><title>Item 1</title><link>https://example.com/item1</link></item></rdf:RDF>"""
    entries = parse_feed(rdf)
    assert len(entries) == 1
    assert entries[0]["link"] == "https://example.com/item1"
    assert entries[0]["title"] == "Item 1"

    # empty
    assert parse_feed("") == []
    assert parse_feed("not xml") == []


_POLLER_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item><title>E1</title><link>https://example.com/p1</link><guid>https://example.com/p1</guid></item><item><title>E2</title><link>https://example.com/p2</link></item></channel></rss>"""


def _stub_poller(monkeypatch):
    """F-1: skip real DNS and the real background pipeline."""
    import vozonda_api.main as main_mod
    import vozonda_api.watchlist_poller as poll_mod

    async def _noop(job_id, runner=None):
        return None

    monkeypatch.setattr(main_mod, "_run", _noop)
    monkeypatch.setattr(poll_mod, "guard_url", lambda url: None)


def _make_poller_watchlist():
    import vozonda_api.watchlist as wl_mod

    return wl_mod.create_watchlist("https://example.com/feed.xml", "balanced", "dialog", "auto", 2)


def test_poller_creates_jobs_for_new_urls(jobs_db, monkeypatch):
    import asyncio

    import vozonda_api.jobs as jobs_mod
    import vozonda_api.watchlist_poller as poll_mod

    _stub_poller(monkeypatch)
    wl = _make_poller_watchlist()

    async def mock_fetch(url):
        return _POLLER_RSS

    monkeypatch.setattr(poll_mod, "fetch_feed_text", mock_fetch)

    store = jobs_mod.JobStore()

    async def run():
        created = await poll_mod.poll_single(wl, store, {}, {}, is_manual=True)
        assert len(created) == 2
        # check watchlist_id stored
        import sqlite3

        with sqlite3.connect(jobs_mod.DB_PATH) as c:
            rows = c.execute("SELECT url, watchlist_id FROM jobs").fetchall()
        assert len(rows) == 2
        assert all(r[1] == wl["id"] for r in rows)

    asyncio.run(run())


def test_poller_second_poll_returns_empty_for_seeded_db(jobs_db, monkeypatch):
    import asyncio

    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod
    import vozonda_api.watchlist_poller as poll_mod
    from vozonda_api.watchlist import record_seen_entry

    _stub_poller(monkeypatch)
    wl = _make_poller_watchlist()

    async def mock_fetch(url):
        return _POLLER_RSS

    monkeypatch.setattr(poll_mod, "fetch_feed_text", mock_fetch)

    store = jobs_mod.JobStore()
    # Seed the DB the way a first poll would: jobs plus seen entries.
    for link in ("https://example.com/p1", "https://example.com/p2"):
        jid = main_mod._readable_id(link)
        store.create(jid, link, "balanced", "dialog", "neutral", "auto", watchlist_id=wl["id"])
        record_seen_entry(link, "seed", first_seen=1000.0, job_id=jid, watchlist_id=wl["id"])

    async def run():
        created = await poll_mod.poll_single(wl, store, {}, {}, is_manual=True)
        assert len(created) == 0

    asyncio.run(run())
