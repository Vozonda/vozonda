"""Per-show Nostr opt-in, review findings F-3 and F-4 of NOSTR-1 (coordinator, 2026-10-02).

Operator rule: Nostr publishing is switched on deliberately per show. The global
nostr.publish_default is only the preset a NEW show starts with; re-saving an existing
show must not overwrite its switch, deleting a show removes its switch, and the show's
key (its Nostr identity) is never deleted silently."""
import logging

import pytest
from fastapi.testclient import TestClient

from vozonda_api import settings_store as ss
from vozonda_api.jobs import init_db
from vozonda_api.main import app


@pytest.fixture(autouse=True)
def _own_db(tmp_path, monkeypatch):
    """settings_store binds DB_PATH at import; both copies must point at this test's DB,
    or a preset set here leaks into every later test."""
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "jobs.db")
    init_db()
    ss.ensure_table()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
    monkeypatch.delenv("VOZONDA_ENABLE_BILLING", raising=False)
    return TestClient(app)


def test_a_new_show_starts_with_the_preset(client):
    ss.set_setting("nostr.publish_default", "1")
    slug = client.post("/shows", json={"name": "Fresh"}).json()["slug"]
    assert ss.get_setting(f"show.{slug}.nostr") == "1"


def test_saving_an_existing_show_keeps_its_switch(client):
    slug = client.post("/shows", json={"name": "Quiet Show"}).json()["slug"]
    assert ss.get_setting(f"show.{slug}.nostr") == "0"
    ss.set_setting("nostr.publish_default", "1")
    assert client.post("/shows", json={"name": "Quiet Show", "author": "New", "slug": slug}).status_code == 200
    assert ss.get_setting(f"show.{slug}.nostr") == "0", "the global preset must not switch an existing show on"


def test_deleting_a_show_removes_its_switch_and_keeps_the_key_loudly(client, monkeypatch, caplog):
    slug = client.post("/shows", json={"name": "Gone"}).json()["slug"]
    ss.set_setting(f"show.{slug}.nostr", "1")
    monkeypatch.setattr("vozonda_api.podcast_key.has_keypair", lambda show_id: True)
    with caplog.at_level(logging.INFO):
        assert client.delete(f"/shows/{slug}").status_code == 200
    assert ss.get_setting(f"show.{slug}.nostr") is None
    assert any("key" in r.getMessage() and "kept" in r.getMessage() for r in caplog.records)


def test_only_numbered_show_switches_are_valid_setting_keys():
    assert ss.set_setting("show.3.nostr", "1") == "1"
    for bad in ("foo.nostr", "show.x.nostr", "show..nostr", "show.3.extra.nostr"):
        with pytest.raises(KeyError):
            ss.get_setting(bad)
        with pytest.raises(KeyError):
            ss.set_setting(bad, "1")


def test_resolve_show_nostr_publishes_only_on_the_shows_own_switch():
    ss.set_setting("nostr.publish_default", "1")
    assert ss.resolve_show_nostr("77") == "0"
    ss.set_setting("show.77.nostr", "1")
    assert ss.resolve_show_nostr("77") == "1"
