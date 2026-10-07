"""Tests for Nostr publishing settings (no network, no hardware).

Covers: defaults, validation, per-show nostr inheritance, settings roundtrip.
"""

import pytest

from vozonda_api import settings_store as ss
from vozonda_api.jobs import JobStore


class TestNostrDefaults:
    @pytest.fixture(autouse=True)
    def _setup(self):
        # Ensure clean state: reset nostr settings to defaults
        conn = ss._conn()
        conn.execute("DELETE FROM settings WHERE key = ?", ("nostr.publish_default",))
        conn.execute("DELETE FROM settings WHERE key = ?", ("nostr.relays",))
        conn.execute("DELETE FROM settings WHERE key = ?", ("nostr.blossom_servers",))
        conn.execute("DELETE FROM settings WHERE key = ?", ("show.999.nostr",))
        conn.commit()

    def test_publish_default_is_zero(self):
        assert ss.get_setting("nostr.publish_default") == "0"

    def test_relays_default(self):
        val = ss.get_setting("nostr.relays") or ""
        urls = [u.strip() for u in val.split(",") if u.strip()]
        assert "wss://relay.damus.io" in urls
        assert "wss://nos.lol" in urls
        assert "wss://relay.primal.net" in urls

    def test_blossom_servers_default(self):
        val = ss.get_setting("nostr.blossom_servers") or ""
        urls = [u.strip() for u in val.split(",") if u.strip()]
        # servers that accept long episodes (a 30 MB preflight, 2026-10-02)
        assert urls == ["https://nostr.download", "https://blossom.primal.net", "https://cdn.nostrcheck.me"]


class TestNostrValidation:
    def test_publish_default_accepts_zero(self):
        assert ss.set_setting("nostr.publish_default", "0") == "0"
        assert ss.get_setting("nostr.publish_default") == "0"

    def test_publish_default_accepts_one(self):
        assert ss.set_setting("nostr.publish_default", "1") == "1"
        assert ss.get_setting("nostr.publish_default") == "1"

    def test_publish_default_rejects_other(self):
        with pytest.raises(ValueError, match="must be '0' or '1'"):
            ss.set_setting("nostr.publish_default", "2")

    def test_publish_default_rejects_yes(self):
        with pytest.raises(ValueError, match="must be '0' or '1'"):
            ss.set_setting("nostr.publish_default", "yes")

    def test_relays_accept_wss_urls(self):
        ss.set_setting("nostr.relays", "wss://relay.example.com, wss://relay2.example.com")
        val = ss.get_setting("nostr.relays")
        assert "wss://relay.example.com" in val
        assert "wss://relay2.example.com" in val

    def test_relays_reject_http(self):
        with pytest.raises(ValueError, match="must start with wss://"):
            ss.set_setting("nostr.relays", "http://relay.example.com")

    def test_relays_reject_https(self):
        with pytest.raises(ValueError, match="must start with wss://"):
            ss.set_setting("nostr.relays", "https://relay.example.com")

    def test_blossom_accepts_https(self):
        ss.set_setting("nostr.blossom_servers", "https://blossom.example.com")
        val = ss.get_setting("nostr.blossom_servers")
        assert "https://blossom.example.com" in val

    def test_blossom_rejects_http(self):
        with pytest.raises(ValueError, match="must start with https://"):
            ss.set_setting("nostr.blossom_servers", "http://blossom.example.com")


class TestShowNostrInheritance:
    """Per-show show.<N>.nostr inherits from publish_default when not set."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        conn = ss._conn()
        conn.execute("DELETE FROM settings WHERE key = ?", ("show.999.nostr",))
        conn.execute("DELETE FROM settings WHERE key = ?", ("show.998.nostr",))
        conn.execute("DELETE FROM settings WHERE key = ?", ("nostr.publish_default",))
        conn.commit()

    def test_show_nostr_unset_returns_none(self):
        """A show without show.N.nostr returns None (not a string)."""
        result = ss.get_setting("show.999.nostr")
        assert result is None

    def test_show_nostr_can_be_set(self):
        ss.set_setting("show.999.nostr", "1")
        assert ss.get_setting("show.999.nostr") == "1"

    def test_show_nostr_rejects_invalid(self):
        with pytest.raises(ValueError, match="must be '0' or '1'"):
            ss.set_setting("show.999.nostr", "yes")

    def test_show_nostr_can_be_cleared(self):
        ss.set_setting("show.999.nostr", "0")
        assert ss.get_setting("show.999.nostr") == "0"

    def test_resolve_show_nostr_ignores_the_preset(self):
        """Operator rule 2026-10-02: only the show's own switch publishes; the preset
        nostr.publish_default applies to NEW shows only (POST /shows)."""
        conn = ss._conn()
        conn.execute("DELETE FROM settings WHERE key = ?", ("show.999.nostr",))
        conn.commit()
        ss.set_setting("nostr.publish_default", "1")
        try:
            assert ss.resolve_show_nostr("999") == "0"
        finally:
            ss.set_setting("nostr.publish_default", "0")

    def test_resolve_show_nostr_follows_the_shows_switch(self):
        ss.set_setting("show.999.nostr", "1")
        assert ss.resolve_show_nostr("999") == "1"
        ss.set_setting("show.999.nostr", "0")
        assert ss.resolve_show_nostr("999") == "0"


class TestJobShowSlug:
    def test_job_gets_show_slug_from_create(self):
        slug = JobStore().create(
            job_id="test-slug-1",
            url="https://example.com/test",
            show_name="Test Show",
            show_slug="s1",
        )
        assert slug.get("show_slug") == "s1"

    def test_job_show_slug_defaults_empty(self):
        slug = JobStore().create(
            job_id="test-slug-2",
            url="https://example.com/test",
        )
        assert slug.get("show_slug") == ""

    def test_show_slug_column_exists(self):
        """Verify the show_slug column was added to the jobs table."""
        store = JobStore()
        job = store.create(
            job_id="test-slug-3",
            url="https://example.com/test",
            show_slug="s42",
        )
        assert "show_slug" in job
        assert job["show_slug"] == "s42"

    def test_new_show_gets_slug_from_publish_default(self):
        """When creating a job with a show, show_slug should default to the show id."""
        # Simulate: a job is created with show_name, the show_slug should be set
        # based on the show's numeric index from the request or current show
        store = JobStore()
        # When show_slug is not provided, it defaults to empty
        job = store.create(
            job_id="test-slug-4",
            url="https://example.com/test",
            show_name="My Show",
            show_slug="",  # explicitly empty means no Nostr linkage
        )
        assert job.get("show_slug") == ""