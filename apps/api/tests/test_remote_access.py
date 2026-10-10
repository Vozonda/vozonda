"""Remote access (GHSA-crq5-73gf-fv2h): local use stays open; a request through a reverse proxy needs the
token, a session cookie, the feed key, or a public episode."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

PROXIED = {"X-Forwarded-For": "203.0.113.7"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(main_mod, "MEDIA_DIR", tmp_path)
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_HOST", raising=False)
    monkeypatch.setenv("VOZONDA_PUBLISHED_ON", "loopback")
    store = jobs_mod.JobStore()
    store.create("talk-0123456789ab", "https://example.com/a")
    store.update("talk-0123456789ab", title="Private talk")
    store.finish("talk-0123456789ab")
    (tmp_path / "talk-0123456789ab.mp3").write_bytes(b"ID3audio")
    return TestClient(main_mod.app)


def _token(monkeypatch, value="s3cret"):
    monkeypatch.setenv("VOZONDA_TOKEN", value)


def test_local_requests_stay_open(app):
    assert app.get("/jobs").status_code == 200
    assert app.get("/audio/talk-0123456789ab.mp3").status_code == 200


def test_proxied_request_without_token_is_locked(app):
    res = app.get("/jobs", headers=PROXIED)
    assert res.status_code == 503
    assert "VOZONDA_TOKEN" in res.json()["detail"]
    assert app.get("/settings", headers=PROXIED).status_code == 503
    assert app.post("/jobs", json={"url": "https://example.com"}, headers=PROXIED).status_code == 503


def test_forwarded_header_counts_as_remote(app):
    assert app.get("/jobs", headers={"Forwarded": "for=203.0.113.7"}).status_code == 503


def test_proxied_request_needs_token_then_bearer_works(app, monkeypatch):
    _token(monkeypatch)
    assert app.get("/jobs", headers=PROXIED).status_code == 401
    ok = app.get("/jobs", headers={**PROXIED, "Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    assert app.get("/jobs", headers={**PROXIED, "Authorization": "Bearer wrong"}).status_code == 401


def test_session_cookie_signs_in_the_web_ui(app, monkeypatch):
    _token(monkeypatch)
    status = app.get("/auth/session", headers=PROXIED).json()
    assert status == {"authenticated": False, "required": True, "token_configured": True}
    assert app.post("/auth/session", json={"token": "nope"}, headers=PROXIED).status_code == 401
    res = app.post("/auth/session", json={"token": "s3cret"}, headers=PROXIED)
    assert res.status_code == 200
    cookie = res.headers["set-cookie"]
    assert "vozonda_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
    assert "s3cret" not in cookie  # the cookie is derived from the token, not the token
    assert app.get("/jobs", headers=PROXIED).status_code == 200  # TestClient keeps the cookie
    assert app.get("/audio/talk-0123456789ab.mp3", headers=PROXIED).status_code == 200
    assert app.get("/auth/session", headers=PROXIED).json()["authenticated"] is True


def test_changing_the_token_ends_sessions(app, monkeypatch):
    _token(monkeypatch)
    app.post("/auth/session", json={"token": "s3cret"}, headers=PROXIED)
    _token(monkeypatch, "rotated")
    assert app.get("/jobs", headers=PROXIED).status_code == 401


def test_write_auth_accepts_the_session_cookie(app, monkeypatch):
    _token(monkeypatch)
    app.post("/auth/session", json={"token": "s3cret"}, headers=PROXIED)
    res = app.delete("/jobs/does-not-exist", headers=PROXIED)
    assert res.status_code != 401


def test_private_media_needs_feed_key(app, monkeypatch):
    _token(monkeypatch)
    from vozonda_api.settings_store import get_private_feed_key

    assert app.get("/audio/talk-0123456789ab.mp3", headers=PROXIED).status_code == 404
    assert app.get("/e/talk-0123456789ab", headers=PROXIED).status_code == 404
    assert app.get("/audio/talk-0123456789ab.mp3?key=wrong", headers=PROXIED).status_code == 404
    key = get_private_feed_key()
    assert app.get(f"/audio/talk-0123456789ab.mp3?key={key}", headers=PROXIED).status_code == 200


def test_public_feed_episode_media_is_open(app, monkeypatch):
    _token(monkeypatch)
    import vozonda_api.routers.feeds as feeds_mod

    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda: True)
    assert app.get("/audio/talk-0123456789ab.mp3", headers=PROXIED).status_code == 200
    # the episode list stays private even then
    assert app.get("/jobs", headers=PROXIED).status_code == 401


def test_nostr_published_episode_media_is_open(app, monkeypatch, tmp_path):
    _token(monkeypatch)
    import vozonda_api.jobs as jobs_mod

    with sqlite3.connect(jobs_mod.DB_PATH) as c:
        c.execute("CREATE TABLE IF NOT EXISTS nostr_publish (job_id TEXT, kind INTEGER, event_id TEXT, "
                  "relay_url TEXT, relay_ok INTEGER, server_url TEXT, server_ok INTEGER, published_at REAL)")
        c.execute("INSERT INTO nostr_publish (job_id, kind, event_id) VALUES (?, 54, 'e1')", ("talk-0123456789ab",))
    assert app.get("/audio/talk-0123456789ab.mp3", headers=PROXIED).status_code == 200


def test_public_paths_and_feeds_pass_the_gate(app, monkeypatch):
    _token(monkeypatch)
    assert app.get("/health", headers=PROXIED).status_code == 200
    # the feed answers for itself: private by default, so 404 without the key, never 401
    assert app.get("/feed.xml", headers=PROXIED).status_code == 404
    from vozonda_api.settings_store import get_private_feed_key

    res = app.get(f"/feed.xml?key={get_private_feed_key()}", headers=PROXIED)
    assert res.status_code == 200


def test_private_feed_links_carry_the_key(app, monkeypatch):
    from vozonda_api.settings_store import get_private_feed_key

    key = get_private_feed_key()
    txt = app.get(f"/feed.xml?key={key}").text
    assert f"/audio/talk-0123456789ab.mp3?key={key}" in txt
    assert f"/vtt/talk-0123456789ab.vtt?key={key}" in txt
    # the guid stays stable without the key
    assert "<guid isPermaLink=\"true\">http://testserver/e/talk-0123456789ab</guid>" in txt


def test_new_ids_are_not_guessable():
    from vozonda_api.main import _readable_id

    rid = _readable_id("https://example.com/some-article")
    assert rid.startswith("some-article-")
    assert len(rid.rsplit("-", 1)[1]) == 12


def test_lan_or_vpn_host_name_counts_as_remote(app):
    # a proxy that keeps the original host, or the machine's LAN/VPN name, without X-Forwarded-For
    assert app.get("/jobs", headers={"Host": "vozonda.example.org"}).status_code == 503
    assert app.get("/jobs", headers={"Host": "203.0.113.20:4173"}).status_code == 503


def test_loopback_host_names_stay_local(app):
    for host in ("127.0.0.1:8787", "localhost", "[::1]:8787", "LOCALHOST:4173"):
        assert app.get("/jobs", headers={"Host": host}).status_code == 200, host


def test_extra_local_host_names(app, monkeypatch):
    monkeypatch.setenv("VOZONDA_LOCAL_HOSTNAMES", "testserver, vozonda.lan")
    assert app.get("/jobs", headers={"Host": "vozonda.lan"}).status_code == 200
