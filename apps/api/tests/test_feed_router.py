import email.utils
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _public_feed(monkeypatch):
    import vozonda_api.routers.feeds as feeds_mod

    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda: True)


def test_feed_routes_registered_exactly_once():
    import vozonda_api.main as main_mod
    from vozonda_api.routers.feeds import router

    expected_paths = {
        "/feed/private-url",
        "/feed.xml",
        "/{creator}/{show}/feed.xml",
    }
    # Verify the paths are defined on the feeds router
    router_paths = {r.path for r in router.routes}
    assert router_paths == expected_paths

    # Verify the paths are registered in the main FastAPI app exactly once.
    # FastAPI 0.141 wraps included routers in _IncludedRouter; unwrap it.
    app_paths: list[str] = []
    for r in main_mod.app.routes:
        if hasattr(r, "path") and getattr(r, "path", None):
            app_paths.append(getattr(r, "path"))
        elif type(r).__name__ == "_IncludedRouter":
            for ctx in r.effective_candidates():  # type: ignore[attr-defined]
                app_paths.append(ctx.path)
    for path in expected_paths:
        count = app_paths.count(path)
        assert count == 1, f"Expected {path} to be registered exactly once, found {count}"


def test_feed_xml_matches_expected_output_for_done_jobs(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    store = jobs_mod.JobStore()
    # The golden XML below predates the AI label being on by default (ef8998a); the label
    # in the feed has its own tests in test_ai_disclosure.py, so switch it off here.
    from vozonda_api.settings_store import set_setting

    set_setting("disclosure.ai_label", "0")

    store.create("ep-a", "https://example.com/a")
    store.update("ep-a", title="Alpha", description="First & <ep>", duration_ms=91000)
    store.finish("ep-a")

    store.create("ep-b", "https://example.com/b")
    store.update("ep-b", title="Beta", description="Second ep", duration_ms=125000)
    store.finish("ep-b")

    with sqlite3.connect(tmp_path / "jobs.db") as conn:
        conn.execute("UPDATE jobs SET created_at = 1700000001.0 WHERE id = 'ep-a'")
        conn.execute("UPDATE jobs SET created_at = 1700000002.0 WHERE id = 'ep-b'")

    fixed_now = "Thu, 24 Sep 2026 10:00:00 GMT"
    fixed_pub = "Thu, 24 Sep 2026 09:00:00 GMT"

    def fake_formatdate(timeval=None, localtime=False, usegmt=False):
        if timeval is None:
            return fixed_now
        return fixed_pub

    monkeypatch.setattr(email.utils, "formatdate", fake_formatdate)

    expected_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:atom="http://www.w3.org/2005/Atom" xmlns:podcast="https://podcastindex.org/namespace/1.0">'
        '<channel><title>Vozonda</title>'
        '<link>http://testserver/</link>'
        '<description>Vozonda: Sovereign audio overviews. Your voices, your feeds. Open source &amp; private.</description>'
        '<language>en</language>'
        '<itunes:author>Vozonda</itunes:author>'
        '<itunes:category text="Technology" />'
        '<atom:link href="http://testserver/feed.xml" rel="self" type="application/rss+xml" />'
        f'<lastBuildDate>{fixed_now}</lastBuildDate>'
        '<generator>Vozonda</generator>'
        '<itunes:image href="http://testserver/img/og-default.png" />'
        '<item><title>Beta</title>'
        '<link>http://testserver/e/ep-b</link>'
        '<guid isPermaLink="true">http://testserver/e/ep-b</guid>'
        '<description>Second ep\n\nSource: https://example.com/b</description>'
        '<itunes:summary>Second ep\n\nSource: https://example.com/b</itunes:summary>'
        '<podcast:transcript url="http://testserver/vtt/ep-b.vtt" type="text/vtt" />'
        f'<pubDate>{fixed_pub}</pubDate>'
        '<enclosure url="http://testserver/audio/ep-b.mp3" length="0" type="audio/mpeg" />'
        '<itunes:duration>2:05</itunes:duration></item>'
        '<item><title>Alpha</title>'
        '<link>http://testserver/e/ep-a</link>'
        '<guid isPermaLink="true">http://testserver/e/ep-a</guid>'
        '<description>First &amp; &lt;ep&gt;\n\nSource: https://example.com/a</description>'
        '<itunes:summary>First &amp; &lt;ep&gt;\n\nSource: https://example.com/a</itunes:summary>'
        '<podcast:transcript url="http://testserver/vtt/ep-a.vtt" type="text/vtt" />'
        f'<pubDate>{fixed_pub}</pubDate>'
        '<enclosure url="http://testserver/audio/ep-a.mp3" length="0" type="audio/mpeg" />'
        '<itunes:duration>1:31</itunes:duration></item>'
        '</channel></rss>'
    )

    client = TestClient(main_mod.app)
    res = client.get("/feed.xml")
    assert res.status_code == 200
    assert res.text == expected_xml

    etag = res.headers.get("etag")
    assert etag is not None
    res304 = client.get("/feed.xml", headers={"if-none-match": etag})
    assert res304.status_code == 304
