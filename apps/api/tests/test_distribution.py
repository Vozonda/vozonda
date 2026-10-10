"""Tests for distribution API (VOZONDA-DISTRIBUTION).

Covers:
- show.<n>.rss setting on new/existing/deleted shows
- 404 for a show feed with rss off
- master feed excludes episodes whose show has rss off
- Nostr publishing unaffected by rss switch
- GET /distribution shape including reachable false/null
- PUT /shows/{slug}/rss with write auth
"""

import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import vozonda_api.jobs as jobs_mod
from vozonda_api import settings_store as ss
from vozonda_api.main import app


@pytest.fixture(autouse=True)
def _own_db(tmp_path, monkeypatch):
    """Isolated DB for settings and jobs."""
    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    # Loopback and billing off to keep write auth open
    monkeypatch.setenv("VOZONDA_HOST", "127.0.0.1")
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_PUBLIC_URL", raising=False)

    jobs_mod.init_db()
    ss.ensure_table()

    # Create settings table
    conn = sqlite3.connect(str(jobs_mod.DB_PATH))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    yield


@pytest.fixture
def client():
    return TestClient(app)


def _create_show(client, name: str, slug: str | None = None, auth_header: str | None = None) -> str:
    body = {"name": name}
    if slug:
        body["slug"] = slug
    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header
    return client.post("/shows", json=body, headers=headers).json()["slug"]


def _create_job(
    client, job_id: str, show_slug: str = "", state: str = "done"
) -> None:
    """Insert a job directly into the test DB."""
    conn = sqlite3.connect(str(jobs_mod.DB_PATH))
    conn.execute(
        "INSERT OR REPLACE INTO jobs "
        "(id, url, state, title, created_at, show_slug, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, "https://example.com/1", state, "Test Episode", 1700000000, show_slug, 1700000000),
    )
    conn.commit()
    conn.close()


def _show_num_from_slug(slug: str) -> str:
    """Extract numeric index from slug (s1 -> 1, 1 -> 1)."""
    return slug.lstrip("s")


def _set_show_rss(slug: str, value: str) -> None:
    num = _show_num_from_slug(slug)
    ss.set_setting(f"show.{num}.rss", value)


def _set_show_nostr(slug: str, value: str) -> None:
    num = _show_num_from_slug(slug)
    ss.set_setting(f"show.{num}.nostr", value)


class TestShowRssPreset:
    """A NEW show takes distribution.rss_default; existing keeps its value; deleting removes it."""

    def test_new_show_uses_rss_default(self, client):
        ss.set_setting("distribution.rss_default", "1")
        slug = _create_show(client, "Fresh Show")
        assert ss.get_setting(f"show.{_show_num_from_slug(slug)}.rss") == "1"

        ss.set_setting("distribution.rss_default", "0")
        slug2 = _create_show(client, "Another Show")
        assert ss.get_setting(f"show.{_show_num_from_slug(slug2)}.rss") == "0"

    def test_existing_show_keeps_its_rss(self, client):
        slug = _create_show(client, "Quiet Show")
        # Default is '1'
        assert ss.get_setting(f"show.{_show_num_from_slug(slug)}.rss") == "1"
        _set_show_rss(slug, "0")
        # Update the show
        assert client.put("/shows/" + slug, json={"name": "Quiet Show", "author": "New"}).status_code == 200
        assert ss.get_setting(f"show.{_show_num_from_slug(slug)}.rss") == "0", "re-saving must not overwrite with preset"

    def test_deleting_show_removes_rss(self, client):
        slug = _create_show(client, "Gone Show")
        _set_show_rss(slug, "1")
        assert client.delete("/shows/" + slug).status_code == 200
        assert ss.get_setting(f"show.{_show_num_from_slug(slug)}.rss") is None


class TestShowRssValidation:
    """Only show.<n>.rss keys are valid."""

    def test_valid_key_accepted(self):
        assert ss.set_setting("show.3.rss", "1") == "1"

    def test_invalid_keys_rejected(self):
        for bad in ("foo.rss", "show.x.rss", "show..rss", "show.3.extra.rss"):
            with pytest.raises(KeyError):
                ss.get_setting(bad)
            with pytest.raises(KeyError):
                ss.set_setting(bad, "1")


class TestResolveShowRss:
    """resolve_show_rss follows the show's own switch, ignores the preset."""

    def _legacy_show(self, num, name):
        conn = sqlite3.connect(str(jobs_mod.DB_PATH))
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (f"show.{num}.name", name))
        conn.commit()
        conn.close()

    def test_legacy_show_without_a_switch_keeps_its_feed(self, client):
        """Every show had a feed before the switch: unset means on (coordinator 2026-10-02;
        the startup backfill that was meant to write it never ran, a NameError at import)."""
        self._legacy_show(99, "Legacy Show")
        assert ss.get_setting("show.99.rss") is None
        assert ss.resolve_show_rss("99") == "1"

    def test_the_new_show_preset_never_turns_off_an_existing_show(self, client):
        """distribution.rss_default is the preset for NEW shows only."""
        ss.set_setting("distribution.rss_default", "0")
        self._legacy_show(88, "Legacy Show Zero")
        assert ss.resolve_show_rss("88") == "1"

    def test_an_explicit_off_is_respected(self, client):
        """Only an explicit '0' turns a show's feed off."""
        ss.set_setting("distribution.rss_default", "1")
        conn = sqlite3.connect(str(jobs_mod.DB_PATH))
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("show.77.name", "Existing RSS Show"),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("show.77.rss", "0"),
        )
        conn.commit()
        conn.close()
        ss.ensure_table()
        # Existing rss=0 should be preserved
        assert ss.get_setting("show.77.rss") == "0"
        assert ss.resolve_show_rss("77") == "0"

    def test_follows_show_switch(self):
        ss.set_setting("show.42.rss", "1")
        assert ss.resolve_show_rss("42") == "1"
        ss.set_setting("show.42.rss", "0")
        assert ss.resolve_show_rss("42") == "0"


class TestFeedRssSwitch:
    """Per-show feed returns 404 when rss=0; master feed excludes episodes with rss=0."""

    def test_per_show_feed_404_when_rss_off(self, client, monkeypatch):
        import vozonda_api.routers.feeds as feeds_mod

        monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda *a, **k: True)

        slug = _create_show(client, "No RSS Show")
        _set_show_rss(slug, "0")
        _create_job(client, "ep-1", show_slug="No RSS Show")

        # Per-show feed URL uses show name (with spaces), not the s{N} slug
        resp = client.get(f"/{slug}/No%20RSS%20Show/feed.xml")
        assert resp.status_code == 404

    def test_per_show_feed_works_when_rss_on(self, client, monkeypatch):
        import vozonda_api.routers.feeds as feeds_mod

        monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda *a, **k: True)

        slug = _create_show(client, "RSS Show")
        _set_show_rss(slug, "1")
        _create_job(client, "ep-1", show_slug="RSS Show")

        resp = client.get(f"/{slug}/RSS%20Show/feed.xml")
        assert resp.status_code == 200
        assert "application/rss+xml" in resp.headers.get("content-type", "")

    def test_master_feed_excludes_rss_off_show(self, client, monkeypatch):
        import vozonda_api.routers.feeds as feeds_mod

        monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda *a, **k: True)

        slug_on = _create_show(client, "RSS On")
        _set_show_rss(slug_on, "1")
        _create_job(client, "ep-on", show_slug="RSS On")

        slug_off = _create_show(client, "RSS Off")
        _set_show_rss(slug_off, "0")
        _create_job(client, "ep-off", show_slug="RSS Off")

        resp = client.get("/feed.xml")
        assert resp.status_code == 200
        # Only ep-on should appear
        assert "ep-on" in resp.text
        assert "ep-off" not in resp.text

    def test_master_feed_excludes_rss_off_show_numeric_slug(self, client, monkeypatch):
        """Regression for F-1: production stores jobs.show_slug as the numeric
        show index (via _show_index_for), not the show name."""
        import vozonda_api.routers.feeds as feeds_mod

        monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda *a, **k: True)

        slug_on = _create_show(client, "RSS On Num")
        _set_show_rss(slug_on, "1")
        _create_job(client, "ep-on-num", show_slug=_show_num_from_slug(slug_on))

        slug_off = _create_show(client, "RSS Off Num")
        _set_show_rss(slug_off, "0")
        _create_job(client, "ep-off-num", show_slug=_show_num_from_slug(slug_off))

        resp = client.get("/feed.xml")
        assert resp.status_code == 200
        assert "ep-on-num" in resp.text
        assert "ep-off-num" not in resp.text

    def test_master_feed_includes_no_show_jobs(self, client, monkeypatch):
        """Jobs with no show_slug (empty) are included in master feed."""
        import vozonda_api.routers.feeds as feeds_mod

        monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda *a, **k: True)

        _create_job(client, "ep-no-show", show_slug="")

        resp = client.get("/feed.xml")
        assert resp.status_code == 200
        assert "ep-no-show" in resp.text


class TestNostrUnaffectedByRss:
    """Nostr publishing follows show.<n>.nostr only; rss switch does not affect it."""

    def test_resolve_show_nostr_independent_of_rss(self):
        _set_show_nostr("s1", "1")
        _set_show_rss("s1", "0")
        assert ss.resolve_show_nostr("1") == "1"
        assert ss.resolve_show_rss("1") == "0"

        _set_show_nostr("s1", "0")
        _set_show_rss("s1", "1")
        assert ss.resolve_show_nostr("1") == "0"
        assert ss.resolve_show_rss("1") == "1"


class TestDistributionEndpoint:
    """GET /distribution shape: defaults, public_url, reachable, per-show data."""

    def test_defaults_and_shows(self, client):
        ss.set_setting("distribution.rss_default", "1")
        ss.set_setting("nostr.publish_default", "0")

        slug = _create_show(client, "Test Show")
        _set_show_rss(slug, "1")
        _set_show_nostr(slug, "0")

        resp = client.get("/distribution")
        assert resp.status_code == 200
        data = resp.json()

        assert data["defaults"]["rss_default"] == "1"
        assert data["defaults"]["nostr_publish_default"] == "0"
        assert data["public_url"] is None
        assert data["reachable"] is None
        assert len(data["shows"]) == 1
        show = data["shows"][0]
        assert show["slug"] == slug
        assert show["name"] == "Test Show"
        assert show["rss"] == "1"
        assert show["nostr"] == "0"
        assert show["feed_url"] is not None
        # feeds are private by default, so the link to copy carries the key
        path, _, query = show["feed_url"].partition("?")
        assert path.endswith(f"/{slug}/Test-Show/feed.xml")
        assert query.startswith("key=")
        # Directory help is static
        assert "apple_podcasts_connect" in data["directory_help"]
        assert "spotify_for_creators" in data["directory_help"]
        assert "podcast_index" in data["directory_help"]

    def test_reachable_false_when_public_url_set_but_unreachable(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_PUBLIC_URL", "https://unreachable.example.com")

        async def mock_get(*args, **kwargs):
            raise httpx.ConnectError("connection failed")

        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=mock_get)):
            resp = client.get("/distribution")

        assert resp.status_code == 200
        data = resp.json()
        assert data["public_url"] == "https://unreachable.example.com"
        assert data["reachable"] is False

    def test_reachable_true_when_public_url_healthy(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_PUBLIC_URL", "https://healthy.example.com")

        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_response)):
            resp = client.get("/distribution")

        assert resp.status_code == 200
        data = resp.json()
        assert data["public_url"] == "https://healthy.example.com"
        assert data["reachable"] is True


class TestPutShowRss:
    """PUT /shows/{slug}/rss with write auth."""

    def test_enable_rss(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_TOKEN", "test-token")
        auth = "Bearer test-token"
        slug = _create_show(client, "Toggle Show", auth_header=auth)
        _set_show_rss(slug, "0")

        resp = client.put(
            f"/shows/{slug}/rss",
            json={"enabled": True},
            headers={"Authorization": auth},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == slug
        assert data["rss"] == "1"
        assert data["feed_url"] is not None

    def test_disable_rss(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_TOKEN", "test-token")
        auth = "Bearer test-token"
        slug = _create_show(client, "Toggle Show", auth_header=auth)
        _set_show_rss(slug, "1")

        resp = client.put(
            f"/shows/{slug}/rss",
            json={"enabled": False},
            headers={"Authorization": auth},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rss"] == "0"
        assert data["feed_url"] is None

    def test_requires_write_auth(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_TOKEN", "test-token")
        auth = "Bearer test-token"
        slug = _create_show(client, "Toggle Show", auth_header=auth)

        resp = client.put(f"/shows/{slug}/rss", json={"enabled": True})
        assert resp.status_code == 401

    def test_rejects_invalid_enabled(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_TOKEN", "test-token")
        auth = "Bearer test-token"
        slug = _create_show(client, "Toggle Show", auth_header=auth)

        resp = client.put(
            f"/shows/{slug}/rss",
            json={"enabled": "yes"},
            headers={"Authorization": auth},
        )
        assert resp.status_code == 422

    def test_404_for_unknown_show(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_TOKEN", "test-token")

        resp = client.put(
            "/shows/999/rss",
            json={"enabled": True},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 404

    def test_404_for_invalid_slug(self, client, monkeypatch):
        monkeypatch.setenv("VOZONDA_TOKEN", "test-token")

        resp = client.put(
            "/shows/abc/rss",
            json={"enabled": True},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 404

def test_a_show_from_before_the_switch_keeps_its_feed(tmp_path, monkeypatch):
    """Coordinator 2026-10-02: an unset show.<n>.rss means on (every show had a feed);
    only an explicit '0' turns it off."""
    import vozonda_api.jobs as jobs_mod
    from vozonda_api import settings_store as ss

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    jobs_mod.init_db()
    ss.ensure_table()
    assert ss.resolve_show_rss("7") == "1"
    ss.set_setting("show.7.rss", "0")
    assert ss.resolve_show_rss("7") == "0"


def test_feed_urls_carry_the_key_when_the_feed_is_private(monkeypatch):
    """A private feed answers only with its key; the link the settings offer to copy must carry it."""
    from fastapi.testclient import TestClient

    import vozonda_api.main as main_mod
    import vozonda_api.routers.feeds as feeds_mod
    from vozonda_api.settings_store import get_private_feed_key, set_setting

    set_setting("show.name", "Default Show")
    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda *a, **k: False)
    data = TestClient(main_mod.app).get("/distribution").json()
    default = next(s for s in data["shows"] if s["slug"] == "default")
    assert data["feed_private"] is True
    if default["feed_url"]:
        assert default["feed_url"].endswith(f"/feed.xml?key={get_private_feed_key()}")

    monkeypatch.setattr(feeds_mod, "_feed_is_public", lambda *a, **k: True)
    data = TestClient(main_mod.app).get("/distribution").json()
    assert data["feed_private"] is False
    assert all("key=" not in (s["feed_url"] or "") for s in data["shows"])
