"""Who can listen (#56): private/public per show, filtered master feed, the address for other devices,
key rotation. Fixtures and helpers as in test_distribution.py."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import vozonda_api.jobs as jobs_mod
from vozonda_api import settings_store as ss
from vozonda_api.main import app


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
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _show(client, name):
    return client.post("/shows", json={"name": name}).json()["slug"]


def _job(job_id, show_slug=""):
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("INSERT OR REPLACE INTO jobs (id, url, state, title, created_at, show_slug, updated_at) "
                  "VALUES (?, ?, 'done', ?, 1700000000, ?, 1700000000)",
                  (job_id, "https://example.com/" + job_id, job_id, show_slug))


def _feed_path(client, slug):
    show = next(s for s in client.get("/distribution").json()["shows"] if s["slug"] == slug)
    return show["feed_url"].split("testserver", 1)[1].split("?")[0]


# ---- per-show private/public ----------------------------------------------------------------------

def test_private_show_feed_needs_the_key_public_show_does_not(client):
    ss.set_setting("show.name", "Main")
    priv, pub = _show(client, "Memo"), _show(client, "Talk")
    ss.set_setting(f"show.{pub[1:]}.public", "1")
    key = ss.get_private_feed_key()
    assert client.get(_feed_path(client, priv)).status_code == 404
    assert client.get(_feed_path(client, priv) + f"?key={key}").status_code == 200
    assert client.get(_feed_path(client, pub)).status_code == 200


def test_master_feed_without_key_lists_only_public_shows(client):
    ss.set_setting("show.name", "Main")
    priv, pub = _show(client, "Memo"), _show(client, "Talk")
    ss.set_setting(f"show.{pub[1:]}.public", "1")
    _job("ep-private", priv)
    _job("ep-public", pub)
    txt = client.get("/feed.xml").text
    assert "ep-public" in txt and "ep-private" not in txt
    key = ss.get_private_feed_key()
    txt = client.get(f"/feed.xml?key={key}").text
    assert "ep-public" in txt and "ep-private" in txt


def test_master_feed_is_404_without_key_when_nothing_is_public(client):
    ss.set_setting("show.name", "Main")
    _job("ep-a")
    assert client.get("/feed.xml").status_code == 404


def test_private_episodes_keep_the_key_in_a_master_feed_whose_default_show_is_public(client):
    """With the key, a private episode's media links carry it even when the default show is public."""
    ss.set_setting("show.name", "Main")
    ss.set_setting("show.default.public", "1")
    priv = _show(client, "Memo")
    _job("ep-private", priv)
    _job("ep-default")
    key = ss.get_private_feed_key()
    txt = client.get(f"/feed.xml?key={key}").text
    assert f"/audio/ep-private.mp3?key={key}" in txt
    assert "/audio/ep-default.mp3\"" in txt  # a public episode's link stays without the key


def test_old_global_feed_public_still_applies_to_shows_without_their_own_value(client):
    """Shows from before this release have no show.<n>.public: they keep following feed.public."""
    ss.set_setting("show.name", "Main")
    ss.set_setting("feed.public", "1")
    slug = _show(client, "Talk")
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:  # as if the show existed before the per-show switch
        c.execute("DELETE FROM settings WHERE key = ?", (f"show.{slug[1:]}.public",))
    assert ss.resolve_show_public(slug[1:]) == "1"
    assert ss.resolve_show_public("default") == "1"
    ss.set_setting(f"show.{slug[1:]}.public", "0")
    assert ss.resolve_show_public(slug[1:]) == "0"


def test_put_show_public(client):
    ss.set_setting("show.name", "Main")
    slug = _show(client, "Talk")
    assert client.put(f"/shows/{slug}/public", json={"enabled": True}).json()["public"] == "1"
    assert ss.resolve_show_public(slug[1:]) == "1"
    assert client.put("/shows/default/public", json={"enabled": False}).json()["public"] == "0"
    assert client.put("/shows/s99/public", json={"enabled": True}).status_code == 404
    assert client.put(f"/shows/{slug}/public", json={"enabled": "yes"}).status_code == 422


def test_job_is_public_follows_its_show(client):
    from vozonda_api import access

    ss.set_setting("show.name", "Main")
    priv, pub = _show(client, "Memo"), _show(client, "Talk")
    ss.set_setting(f"show.{pub[1:]}.public", "1")
    assert access.job_is_public({"id": "a", "show_slug": pub}) is True
    assert access.job_is_public({"id": "b", "show_slug": priv}) is False


def test_distribution_reports_public_per_show_and_keys_only_private_links(client):
    ss.set_setting("show.name", "Main")
    priv, pub = _show(client, "Memo"), _show(client, "Talk")
    ss.set_setting(f"show.{pub[1:]}.public", "1")
    data = client.get("/distribution").json()
    shows = {s["slug"]: s for s in data["shows"]}
    assert shows[pub]["public"] == "1" and "key=" not in shows[pub]["feed_url"]
    assert shows[priv]["public"] == "0" and "key=" in shows[priv]["feed_url"]
    assert data["feed_private"] is True


# ---- key rotation ----------------------------------------------------------------------------------

def test_rotating_the_key_stops_old_links(client):
    ss.set_setting("show.name", "Main")
    _job("ep-a")
    old = ss.get_private_feed_key()
    assert client.get(f"/feed.xml?key={old}").status_code == 200
    new = client.post("/feed/key/rotate").json()["key"]
    assert new != old
    assert client.get(f"/feed.xml?key={old}").status_code == 404
    assert client.get(f"/feed.xml?key={new}").status_code == 200


# ---- the address other devices use -----------------------------------------------------------------

@pytest.mark.parametrize("url, scope", [
    ("http://127.0.0.1:4173", "this-computer"),
    ("http://localhost:4173", "this-computer"),
    ("http://vozonda.example.ts.net:4173", "private-network"),
    ("http://100.100.1.2:4173", "private-network"),
    ("http://192.168.1.5:4173", "private-network"),
    ("https://pods.example.org", "internet"),
])
def test_address_scope(client, url, scope):
    ss.set_setting("address.public", url)
    addr = client.get("/distribution").json()["address"]
    assert addr["scope"] == scope and addr["source"] == "setting" and addr["url"] == url


def test_address_setting_wins_over_the_env_and_goes_into_feed_links(client, monkeypatch):
    monkeypatch.setenv("VOZONDA_PUBLIC_URL", "https://env.example.org")
    ss.set_setting("show.name", "Main")
    ss.set_setting("show.default.public", "1")
    _job("ep-a")
    assert "https://env.example.org/audio/ep-a.mp3" in client.get("/feed.xml").text
    ss.set_setting("address.public", "https://pods.example.org/")
    txt = client.get("/feed.xml").text
    assert "https://pods.example.org/audio/ep-a.mp3" in txt and "env.example.org" not in txt
    assert client.get("/distribution").json()["address"]["source"] == "setting"


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://x.example.org", "https://x.example.org/?a=1",
                                 'https://x.example.org/"><script>', "https://user:pw@example.org"])
def test_address_must_be_a_plain_http_address(bad):
    with pytest.raises(ValueError):
        ss.set_setting("address.public", bad)


def test_address_can_be_cleared(client):
    ss.set_setting("address.public", "https://pods.example.org")
    ss.set_setting("address.public", "")
    assert client.get("/distribution").json()["address"]["source"] == "none"


# ---- which show an episode belongs to ------------------------------------------------------------

def test_episode_of_a_deleted_show_does_not_break_the_master_feed(client):
    """_show_num_for_slug returns None for a deleted show; the feed used to ask for 'show.None.rss' (500)."""
    ss.set_setting("show.name", "Main")
    ss.set_setting("show.default.public", "1")
    _job("ep-orphan", "s42")
    res = client.get("/feed.xml")
    assert res.status_code == 200 and "ep-orphan" in res.text  # follows the default show


def test_show_is_found_by_name_after_a_gap(client):
    from vozonda_api.routers.feeds import _job_show_num

    ss.set_setting("show.name", "Main")
    first, second = _show(client, "First"), _show(client, "Second Show")
    client.delete(f"/shows/{first}")
    assert _job_show_num({"show_slug": "", "show_name": "Second Show"}) == second[1:]


def test_feed_and_media_gate_agree_for_an_episode_known_by_its_show_name(client):
    from vozonda_api import access
    from vozonda_api.routers.feeds import _public_checker

    ss.set_setting("show.name", "Main")
    pub = _show(client, "Talk")
    ss.set_setting(f"show.{pub[1:]}.public", "1")
    job = {"id": "x", "show_slug": "", "show_name": "Talk"}
    assert _public_checker()(job) is True and access.job_is_public(job) is True


def test_watchlist_episodes_follow_the_watchlists_show(client):
    """A digest episode has no show_slug; it belongs to its watchlist's show, in the master feed, in the
    watchlist's own feed and at the media gate alike."""
    from vozonda_api import access
    from vozonda_api.watchlist import create_watchlist, update_watchlist

    ss.set_setting("show.name", "Main")
    ss.set_setting("show.default.public", "1")
    priv = _show(client, "Memo")
    wl = create_watchlist("https://example.org/rss.xml")
    update_watchlist(wl["id"], show_slug=priv)
    with sqlite3.connect(str(jobs_mod.DB_PATH)) as c:
        c.execute("INSERT INTO jobs (id, url, state, title, created_at, show_slug, updated_at, watchlist_id) "
                  "VALUES ('digest-1', 'digest:x', 'done', 'Digest', 1700000000, '', 1700000000, ?)", (wl["id"],))
    _job("ep-default")
    txt = client.get("/feed.xml").text
    assert "ep-default" in txt and "digest-1" not in txt
    assert access.job_is_public({"id": "digest-1", "show_slug": "", "watchlist_id": wl["id"]}) is False
    assert client.get(f"/x/{wl['id']}/feed.xml").status_code == 404  # private: needs the key
    key = ss.get_private_feed_key()
    assert "digest-1" in client.get(f"/x/{wl['id']}/feed.xml?key={key}").text
    ss.set_setting(f"show.{priv[1:]}.public", "1")
    assert client.get(f"/x/{wl['id']}/feed.xml").status_code == 200


def test_a_new_show_starts_private_even_when_the_old_global_switch_is_public(client):
    ss.set_setting("show.name", "Main")
    ss.set_setting("feed.public", "1")
    slug = _show(client, "Fresh")
    assert ss.resolve_show_public(slug[1:]) == "0"
    assert ss.resolve_show_public("default") == "1"  # existing default show keeps the old behaviour


def test_deleting_a_show_removes_its_public_switch(client):
    ss.set_setting("show.name", "Main")
    slug = _show(client, "Talk")
    ss.set_setting(f"show.{slug[1:]}.public", "1")
    client.delete(f"/shows/{slug}")
    assert ss.get_setting(f"show.{slug[1:]}.public") is None
