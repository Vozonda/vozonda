"""VOZONDA-L2: feeds are private by default (key-gated, 404 on wrong key),
the private key is masked in GET /settings, and feed items carry source
attribution."""

import pytest
from fastapi.testclient import TestClient

from vozonda_api import jobs as jobs_mod
from vozonda_api import main as main_mod
from vozonda_api import settings_store as ss


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "vozonda-test.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db)
    monkeypatch.setattr(ss, "DB_PATH", db)
    jobs_mod.init_db()
    ss.ensure_table()
    return TestClient(main_mod.app)


def _make_done_job(job_id: str = "job-test1", url: str = "https://example.com/article") -> None:
    main_mod.store.create(job_id, url, "balanced", "dialog", "neutral", "en", hosts=2)
    main_mod.store.update(job_id, state="done")


def test_feed_404_without_key_when_private(client: TestClient) -> None:
    ss.set_setting("feed.public", "0")
    r = client.get("/feed.xml")
    assert r.status_code == 404


def test_feed_404_with_wrong_key(client: TestClient) -> None:
    ss.set_setting("feed.public", "0")
    ss.get_private_feed_key()
    r = client.get("/feed.xml", params={"key": "wrong-key"})
    assert r.status_code == 404


def test_hierarchical_feed_404_without_key_when_private(client: TestClient) -> None:
    ss.set_setting("feed.public", "0")
    r = client.get("/me/my-show/feed.xml")
    assert r.status_code == 404


def test_feed_200_with_key(client: TestClient) -> None:
    key = ss.get_private_feed_key()
    r = client.get("/feed.xml", params={"key": key})
    assert r.status_code == 200
    assert "<rss" in r.text


def test_feed_200_without_key_when_public(client: TestClient) -> None:
    ss.set_setting("feed.public", "1")
    r = client.get("/feed.xml")
    assert r.status_code == 200
    assert "<rss" in r.text


def test_private_key_masked_in_settings(client: TestClient) -> None:
    real_key = ss.get_private_feed_key()
    r = client.get("/settings")
    assert r.status_code == 200
    settings = r.json()["settings"]
    assert settings.get("feed.private_key") == ss.SECRET_MASK
    assert real_key not in r.text


def test_source_url_in_item_description(client: TestClient) -> None:
    ss.set_setting("feed.public", "1")
    _make_done_job()
    r = client.get("/feed.xml")
    assert r.status_code == 200
    assert "Source: https://example.com/article" in r.text


def test_private_url_endpoint_returns_full_url(client: TestClient) -> None:
    ss.set_setting("feed.public", "0")
    r = client.get("/feed/private-url")
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == ss.get_private_feed_key()
    assert body["url"].endswith(f"/feed.xml?key={body['key']}")
    assert body["public"] is False


def test_feed_is_private_when_the_setting_was_never_saved(client: TestClient) -> None:
    """Private by default means an install that never touched the setting.
    The landed version treated an unset value as public."""
    assert ss.get_setting("feed.public") in (None, "")
    assert client.get("/feed.xml").status_code == 404
    assert client.get(f"/feed.xml?key={ss.get_private_feed_key()}").status_code == 200


def _done_show_job(job_id: str, show: str) -> None:
    main_mod.store.create(job_id, f"https://example.com/{job_id}", "balanced", "dialog", "neutral", "en",
                          hosts=2, show_name=show)
    main_mod.store.update(job_id, state="done")


def test_show_feed_matches_its_show_only_and_ignores_like_wildcards(client: TestClient) -> None:
    ss.set_setting("feed.public", "1")
    _done_show_job("ep-mine", "My Show")
    _done_show_job("ep-other", "Other Show")
    mine = client.get("/me/my-show/feed.xml").text
    assert "ep-mine" in mine and "ep-other" not in mine
    wildcard = client.get("/me/%25/feed.xml").text
    assert "ep-mine" not in wildcard and "ep-other" not in wildcard


def test_show_feed_etag_is_stable_and_has_the_full_channel(client: TestClient) -> None:
    """The per-show feed was a stale copy: its ETag hashed the build time (never
    304) and it lacked the iTunes channel tags."""
    ss.set_setting("feed.public", "1")
    _done_show_job("ep-etag", "My Show")
    first = client.get("/me/my-show/feed.xml")
    assert "<itunes:author>" in first.text and "<itunes:image" in first.text
    again = client.get("/me/my-show/feed.xml", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304


def test_private_feed_self_link_keeps_the_key(client: TestClient) -> None:
    ss.set_setting("feed.public", "0")
    key = ss.get_private_feed_key()
    body = client.get(f"/feed.xml?key={key}").text
    assert f'feed.xml?key={key}" rel="self"' in body


def test_show_feed_etag_survives_an_episode_created_in_the_build_second(client: TestClient, monkeypatch) -> None:
    """The ETag hash blanked every occurrence of the build time, including the
    pubDate of an episode created in that same second; one second later the
    ETag changed and the feed was sent again instead of 304."""
    import email.utils as eu

    from vozonda_api.routers import feeds

    ss.set_setting("feed.public", "1")
    _done_show_job("ep-same-second", "Same Second Show")
    created = main_mod.store.get("ep-same-second")["created_at"]
    monkeypatch.setattr(feeds, "_now_rfc", lambda: eu.formatdate(created, usegmt=True))
    first = client.get("/me/same-second-show/feed.xml")
    monkeypatch.setattr(feeds, "_now_rfc", lambda: eu.formatdate(created + 5, usegmt=True))
    again = client.get("/me/same-second-show/feed.xml", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304
